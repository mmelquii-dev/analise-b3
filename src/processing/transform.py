import math
from pathlib import Path
import sys

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import duckdb
import polars as pl
from rich.console import Console
from rich.table import Table

from src.config import (
    RAW_MACRO_DIR,
    RAW_STOCKS_DIR,
    TICKER_NAMES,
    TRUSTED_DIR,
)

console = Console()


def run_pipeline() -> tuple[Path, Path, Path]:
    """Lê os dados brutos (RAW), processa com DuckDB e Polars, calcula rentabilidade acumulada,

    alinhamento de calendário, métricas de risco (Volatilidade, Sharpe, Max Drawdown)
    e persiste na camada TRUSTED (Parquet + DuckDB).
    """
    stocks_raw_path = RAW_STOCKS_DIR / "raw_stocks.parquet"
    selic_raw_path = RAW_MACRO_DIR / "raw_selic.parquet"

    if not stocks_raw_path.exists() or not selic_raw_path.exists():
        raise FileNotFoundError(
            f"Arquivos da camada RAW não encontrados. Execute a ingestão primeiro.\n"
            f"Esperados: {stocks_raw_path} e {selic_raw_path}"
        )

    TRUSTED_DIR.mkdir(parents=True, exist_ok=True)
    console.print("[bold blue]⚙️ Iniciando Processamento & Transformação (DuckDB + Polars)...[/bold blue]")

    # 1. Carrega dados brutos via DuckDB
    con = duckdb.connect()

    # Identificar a data mínima em comum para todos os ativos terem base 100 honesta
    # Pegamos os últimos 5 anos exatos
    common_start_date = con.execute(f"""
        WITH stock_min_dates AS (
            SELECT ticker, min(date) as min_d, max(date) as max_d
            FROM '{stocks_raw_path}'
            GROUP BY ticker
        ),
        selic_min_date AS (
            SELECT min(date) as min_d FROM '{selic_raw_path}'
        )
        SELECT max(min_d) as start_date
        FROM (
            SELECT min_d FROM stock_min_dates
            UNION ALL
            SELECT min_d FROM selic_min_date
        )
    """).fetchone()[0]

    console.print(f"  • Data base comum para normalização de rentabilidade: [cyan]{common_start_date}[/cyan]")

    # 2. Processamento das Ações e Ibovespa
    stocks_processed_df = con.execute(f"""
        WITH filtered_stocks AS (
            SELECT 
                ticker,
                ticker_name,
                CAST(date AS DATE) as date,
                close,
                adj_close,
                volume
            FROM '{stocks_raw_path}'
            WHERE date >= '{common_start_date}'
        ),
        with_lag AS (
            SELECT 
                ticker,
                ticker_name,
                date,
                close,
                adj_close,
                volume,
                LAG(adj_close) OVER (PARTITION BY ticker ORDER BY date) as prev_adj_close,
                FIRST_VALUE(adj_close) OVER (PARTITION BY ticker ORDER BY date) as initial_adj_close
            FROM filtered_stocks
        )
        SELECT 
            ticker,
            ticker_name,
            date,
            close,
            adj_close,
            volume,
            COALESCE((adj_close / NULLIF(prev_adj_close, 0)) - 1.0, 0.0) as daily_return,
            ROUND(((adj_close / NULLIF(initial_adj_close, 0)) - 1.0) * 100.0, 4) as cumulative_return_pct,
            ROUND((adj_close / NULLIF(initial_adj_close, 0)) * 100.0, 4) as index_base_100
        FROM with_lag
        ORDER BY ticker, date
    """).pl()

    # 3. Processamento da Taxa Selic Acumulada
    # Datas de negociação presentes nas ações para alinhar o calendário da bolsa
    trading_dates = stocks_processed_df.select("date").unique().sort("date")

    selic_raw_df = pl.read_parquet(selic_raw_path).filter(pl.col("date") >= common_start_date).sort("date")

    # Alinha a Selic com as datas de negociação da B3
    selic_aligned = (
        trading_dates
        .join(selic_raw_df, on="date", how="left")
        .with_columns([
            pl.col("daily_factor").fill_null(1.0),
            pl.col("selic_daily_rate").fill_null(0.0),
        ])
    )

    # Calcula retorno diário da Selic e retorno composto acumulado
    factors = selic_aligned["daily_factor"].to_list()
    cum_factors = []
    current_cum = 1.0
    for f in factors:
        current_cum *= f
        cum_factors.append(current_cum)

    selic_aligned = selic_aligned.with_columns(
        pl.Series("cum_factor", cum_factors)
    ).with_columns([
        pl.lit("SELIC").alias("ticker"),
        pl.lit("Taxa Selic Acumulada").alias("ticker_name"),
        pl.col("cum_factor").alias("close"),
        pl.col("cum_factor").alias("adj_close"),
        pl.lit(0.0).alias("volume"),
        (pl.col("daily_factor") - 1.0).alias("daily_return"),
        ((pl.col("cum_factor") - 1.0) * 100.0).round(4).alias("cumulative_return_pct"),
        (pl.col("cum_factor") * 100.0).round(4).alias("index_base_100"),
    ]).select([
        "ticker",
        "ticker_name",
        "date",
        "close",
        "adj_close",
        "volume",
        "daily_return",
        "cumulative_return_pct",
        "index_base_100",
    ])

    # 4. Unificar em uma única tabela analítica (Data Lake Trusted)
    unified_df = pl.concat([
        stocks_processed_df.select([
            "ticker", "ticker_name", "date", "close", "adj_close", "volume", 
            "daily_return", "cumulative_return_pct", "index_base_100"
        ]),
        selic_aligned,
    ]).sort(["ticker", "date"])

    # Salva o Parquet consolidado na camada TRUSTED
    trusted_parquet = TRUSTED_DIR / "market_benchmark_5y.parquet"
    unified_df.write_parquet(trusted_parquet, compression="zstd")

    # 5. Cálculo das Métricas de Risco e Desempenho (KPIs)
    # Total Return, CAGR, Volatilidade Anualizada, Max Drawdown, Índice Sharpe
    kpi_records = []
    
    # Identifica o CAGR da Selic para usar como taxa livre de risco (Risk-Free)
    selic_final_ret = unified_df.filter(pl.col("ticker") == "SELIC")["cumulative_return_pct"].to_list()[-1] / 100.0
    total_days = (unified_df["date"].max() - unified_df["date"].min()).days
    years_elapsed = max(total_days / 365.25, 0.1)
    selic_cagr = (1.0 + selic_final_ret) ** (1.0 / years_elapsed) - 1.0

    for ticker in unified_df["ticker"].unique().to_list():
        ticker_data = unified_df.filter(pl.col("ticker") == ticker).sort("date")
        t_name = ticker_data["ticker_name"][0]
        
        returns = ticker_data["daily_return"].to_list()
        cum_pct = ticker_data["cumulative_return_pct"].to_list()[-1]
        
        # Total return & CAGR
        total_ret = cum_pct / 100.0
        cagr = ((1.0 + total_ret) ** (1.0 / years_elapsed) - 1.0) if (1.0 + total_ret) > 0 else 0.0

        # Volatilidade Anualizada (desvio padrão dos retornos diários * sqrt(252))
        if len(returns) > 1 and ticker != "SELIC":
            mean_ret = sum(returns) / len(returns)
            variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
            daily_std = math.sqrt(variance)
            ann_volatility = daily_std * math.sqrt(252) * 100.0
        else:
            ann_volatility = 0.0

        # Max Drawdown
        prices = ticker_data["index_base_100"].to_list()
        peak = prices[0]
        max_dd = 0.0
        for p in prices:
            if p > peak:
                peak = p
            dd = (p - peak) / peak if peak > 0 else 0.0
            if dd < max_dd:
                max_dd = dd
        max_drawdown_pct = max_dd * 100.0

        # Índice Sharpe simples (CAGR Ativo - CAGR Selic) / Volatilidade Anualizada
        if ann_volatility > 0:
            sharpe_ratio = ((cagr - selic_cagr) * 100.0) / ann_volatility
        else:
            sharpe_ratio = 0.0

        kpi_records.append({
            "ticker": ticker,
            "ticker_name": t_name,
            "retorno_total_pct": round(cum_pct, 2),
            "cagr_anual_pct": round(cagr * 100.0, 2),
            "volatilidade_anual_pct": round(ann_volatility, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
        })

    kpi_df = pl.DataFrame(kpi_records).sort("retorno_total_pct", descending=True)
    kpi_parquet = TRUSTED_DIR / "kpi_metrics.parquet"
    kpi_df.write_parquet(kpi_parquet, compression="zstd")

    # 6. Criar banco DuckDB analítico com Views
    duckdb_path = TRUSTED_DIR / "analytics.duckdb"
    if duckdb_path.exists():
        duckdb_path.unlink()

    duck_con = duckdb.connect(str(duckdb_path))
    duck_con.execute(f"CREATE TABLE market_benchmark AS SELECT * FROM '{trusted_parquet}'")
    duck_con.execute(f"CREATE TABLE kpi_metrics AS SELECT * FROM '{kpi_parquet}'")
    duck_con.close()

    console.print(f"[bold green]✔ Camada TRUSTED criada com sucesso![/bold green]")
    console.print(f"  • Séries temporais: [underline]{trusted_parquet}[/underline] ({trusted_parquet.stat().st_size / 1024:.1f} KB)")
    console.print(f"  • Métricas KPIs: [underline]{kpi_parquet}[/underline]")
    console.print(f"  • Banco DuckDB OLAP: [underline]{duckdb_path}[/underline]")

    # Exibe tabela formatada no terminal
    table = Table(title="📊 Desempenho Histórico vs Selic & Ibovespa (5 Anos)")
    table.add_column("Ativo", style="bold cyan")
    table.add_column("Nome", style="white")
    table.add_column("Retorno Total", justify="right", style="green")
    table.add_column("CAGR Anual", justify="right")
    table.add_column("Volatilidade", justify="right", style="magenta")
    table.add_column("Max Drawdown", justify="right", style="red")
    table.add_column("Índice Sharpe", justify="right", style="yellow")

    for row in kpi_df.iter_rows(named=True):
        ret_style = "green" if row["retorno_total_pct"] >= 0 else "red"
        table.add_row(
            row["ticker"],
            row["ticker_name"],
            f"[{ret_style}]{row['retorno_total_pct']:+.2f}%[/{ret_style}]",
            f"{row['cagr_anual_pct']:+.2f}%",
            f"{row['volatilidade_anual_pct']:.2f}%",
            f"{row['max_drawdown_pct']:.2f}%",
            f"{row['sharpe_ratio']:.2f}",
        )

    console.print(table)

    return trusted_parquet, kpi_parquet, duckdb_path


if __name__ == "__main__":
    run_pipeline()

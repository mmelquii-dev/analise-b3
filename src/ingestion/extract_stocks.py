import datetime
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import polars as pl
import yfinance as yf
from rich.console import Console

from src.config import ALL_TICKERS, RAW_STOCKS_DIR, TICKER_NAMES

console = Console()


def extract_stocks_data(
    tickers: list[str] | None = None,
    years: int = 5,
    output_dir: Path | None = None,
) -> Path:
    """Extrai cotações históricas diárias da B3 via yfinance e salva em formato Parquet (RAW Data Lake)."""
    if tickers is None:
        tickers = ALL_TICKERS
    if output_dir is None:
        output_dir = RAW_STOCKS_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=years * 365 + 30)

    console.print(
        f"[bold blue]📥 Ingestão de Ações (yfinance)[/bold blue]: Baixando histórico de {len(tickers)} ativos de {start_date} a {end_date}..."
    )

    records = []

    for ticker in tickers:
        friendly_name = TICKER_NAMES.get(ticker, ticker)
        console.print(f"  • Baixando [cyan]{ticker}[/cyan] ({friendly_name})...")

        ticker_obj = yf.Ticker(ticker)
        # auto_adjust=False para preservar Close e Adj Close originais
        df_history = ticker_obj.history(start=start_date.isoformat(), end=end_date.isoformat(), auto_adjust=False)

        if df_history.empty:
            console.print(f"  [yellow]⚠️ Nenhum dado retornado para {ticker}![/yellow]")
            continue

        df_history = df_history.reset_index()

        for _, row in df_history.iterrows():
            date_val = row["Date"]
            # Converter timestamp para data (YYYY-MM-DD)
            if hasattr(date_val, "date"):
                date_str = date_val.date().isoformat()
            else:
                date_str = str(date_val)[:10]

            records.append({
                "ticker": ticker,
                "ticker_name": friendly_name,
                "date": date_str,
                "open": float(row.get("Open", 0.0) or 0.0),
                "high": float(row.get("High", 0.0) or 0.0),
                "low": float(row.get("Low", 0.0) or 0.0),
                "close": float(row.get("Close", 0.0) or 0.0),
                "adj_close": float(row.get("Adj Close", row.get("Close", 0.0)) or 0.0),
                "volume": float(row.get("Volume", 0.0) or 0.0),
            })

    if not records:
        raise RuntimeError("Nenhum dado de ações foi coletado com sucesso.")

    # Converte para Polars DataFrame
    df_pl = pl.DataFrame(records).with_columns([
        pl.col("date").str.to_date("%Y-%m-%d"),
    ]).sort(["ticker", "date"])

    output_file = output_dir / "raw_stocks.parquet"
    df_pl.write_parquet(output_file, compression="zstd")

    console.print(
        f"[bold green]✔ Ingestão de ações concluída![/bold green] "
        f"{len(df_pl):,} registros salvos em [bold underline]{output_file}[/bold underline] ({output_file.stat().st_size / 1024:.1f} KB)"
    )

    return output_file


if __name__ == "__main__":
    extract_stocks_data()

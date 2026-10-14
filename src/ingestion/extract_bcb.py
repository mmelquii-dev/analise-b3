import datetime
from pathlib import Path
import sys

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import polars as pl
import requests
from rich.console import Console

from src.config import BCB_SERIES, RAW_MACRO_DIR

console = Console()


def extract_bcb_series(
    series_code: int = 11,
    years: int = 5,
    output_dir: Path | None = None,
) -> Path:
    """Extrai série temporal do Banco Central do Brasil (SGS) via API aberta oficial.

    Série 11: Taxa Selic apurada diária (% ao dia).
    """
    if output_dir is None:
        output_dir = RAW_MACRO_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=years * 365 + 30)

    # API do BACEN SGS espera DD/MM/AAAA
    start_str = start_date.strftime("%d/%m/%Y")
    end_str = end_date.strftime("%d/%m/%Y")

    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados?formato=json&dataInicial={start_str}&dataFinal={end_str}"

    console.print(
        f"[bold blue]📥 Ingestão Macro (BACEN SGS Série {series_code})[/bold blue]: Solicitando dados de {start_str} até {end_str}..."
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) BigData-PoC/1.0"
    }

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        console.print(f"[bold red]❌ Falha ao consultar API do Banco Central:[/bold red] {e}")
        # Tenta fallback sem filtros de data caso a API reclame
        fallback_url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series_code}/dados/ultimos/1500?formato=json"
        console.print(f"[yellow]Tentando endpoint de fallback dos últimos 1500 registros...[/yellow]")
        response = requests.get(fallback_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

    if not data:
        raise RuntimeError("Nenhum dado retornado pela API do Banco Central.")

    # Converte para Polars DataFrame
    # Resposta: [{"data": "01/10/2021", "valor": "0.019800"}, ...]
    df = (
        pl.DataFrame(data)
        .with_columns([
            pl.col("data").str.to_date("%d/%m/%Y").alias("date"),
            pl.col("valor").cast(pl.Float64).alias("selic_daily_rate"),
        ])
        .select(["date", "selic_daily_rate"])
        .filter(pl.col("date") >= pl.lit(start_date))
        .sort("date")
    )

    # Adiciona fator diário (1 + taxa / 100) para cálculo de juros compostos
    df = df.with_columns([
        (1.0 + pl.col("selic_daily_rate") / 100.0).alias("daily_factor"),
    ])

    output_file = output_dir / "raw_selic.parquet"
    df.write_parquet(output_file, compression="zstd")

    console.print(
        f"[bold green]✔ Ingestão BACEN Selic concluída![/bold green] "
        f"{len(df):,} dias úteis salvos em [bold underline]{output_file}[/bold underline] ({output_file.stat().st_size / 1024:.1f} KB)"
    )

    return output_file


if __name__ == "__main__":
    extract_bcb_series(series_code=BCB_SERIES["selic_diaria"])

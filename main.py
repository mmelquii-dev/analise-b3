import argparse
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel

console = Console()


def show_status():
    from src.config import RAW_MACRO_DIR, RAW_STOCKS_DIR, TRUSTED_DIR
    import polars as pl

    console.print(Panel.fit("[bold cyan]Big Data Finance Data Lake - Status das Camadas[/bold cyan]"))

    raw_stocks = RAW_STOCKS_DIR / "raw_stocks.parquet"
    raw_selic = RAW_MACRO_DIR / "raw_selic.parquet"
    trusted_benchmark = TRUSTED_DIR / "market_benchmark_5y.parquet"
    trusted_kpis = TRUSTED_DIR / "kpi_metrics.parquet"
    duckdb_file = TRUSTED_DIR / "analytics.duckdb"

    files = [
        ("RAW - Ações (B3)", raw_stocks),
        ("RAW - Selic (BACEN)", raw_selic),
        ("TRUSTED - Séries Temporais", trusted_benchmark),
        ("TRUSTED - Métricas de Risco", trusted_kpis),
        ("TRUSTED - Banco DuckDB OLAP", duckdb_file),
    ]

    for label, file_path in files:
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            extra = ""
            if file_path.suffix == ".parquet":
                try:
                    df = pl.read_parquet(file_path)
                    extra = f" | {len(df):,} linhas"
                except Exception:
                    pass
            console.print(f"  [green]✔[/green] {label:28}: [cyan]{file_path.name}[/cyan] ({size_kb:.1f} KB{extra})")
        else:
            console.print(f"  [red]✖[/red] {label:28}: [yellow]Não encontrado[/yellow]")


def run_ingest():
    from src.ingestion.extract_stocks import extract_stocks_data
    from src.ingestion.extract_bcb import extract_bcb_series
    from src.config import BCB_SERIES

    console.print(Panel("[bold green]Etapa 1/2: Ingestão de Dados (RAW Data Lake)[/bold green]"))
    extract_stocks_data()
    extract_bcb_series(series_code=BCB_SERIES["selic_diaria"])


def run_transform():
    from src.processing.transform import run_pipeline

    console.print(Panel("[bold green]Etapa 2/2: Processamento Analítico (TRUSTED Data Lake)[/bold green]"))
    run_pipeline()


def run_dashboard():
    dashboard_path = Path(__file__).resolve().parent / "src" / "dashboard" / "app.py"
    console.print(f"[bold blue]🚀 Iniciando Streamlit Dashboard em[/bold blue] [cyan]{dashboard_path}[/cyan]...")
    subprocess.run([
        sys.executable, "-m", "streamlit", "run", str(dashboard_path),
        "--server.headless", "true",
        "--server.address", "0.0.0.0",
        "--server.port", "8501",
    ])


def run_query(sql: str):
    import duckdb
    from src.config import TRUSTED_DIR
    from rich.table import Table

    duckdb_file = TRUSTED_DIR / "analytics.duckdb"
    if not duckdb_file.exists():
        console.print("[red]Banco DuckDB não encontrado. Execute 'python main.py pipeline' primeiro.[/red]")
        return

    con = duckdb.connect(str(duckdb_file), read_only=True)
    res = con.execute(sql).fetchall()
    cols = [d[0] for d in con.description]
    con.close()

    table = Table(title=f"Resultado da Query DuckDB")
    for col in cols:
        table.add_column(col, style="cyan")

    for row in res:
        table.add_row(*[str(val) for val in row])

    console.print(table)


def main():
    parser = argparse.ArgumentParser(description="Big Data Finance Pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", help="Comandos disponíveis")

    subparsers.add_parser("ingest", help="Executa a ingestão das fontes para a camada RAW")
    subparsers.add_parser("transform", help="Executa a transformação e salva na camada TRUSTED")
    subparsers.add_parser("pipeline", help="Executa o pipeline completo (ingestão + transformação)")
    subparsers.add_parser("dashboard", help="Inicia o dashboard interativo no navegador (Streamlit)")
    subparsers.add_parser("status", help="Exibe o status dos arquivos do Data Lake")

    query_parser = subparsers.add_parser("query", help="Executa consulta SQL no DuckDB")
    query_parser.add_argument("sql", type=str, help="Comando SQL a ser executado")

    args = parser.parse_args()

    if args.command == "ingest":
        run_ingest()
    elif args.command == "transform":
        run_transform()
    elif args.command == "pipeline":
        run_ingest()
        run_transform()
    elif args.command == "dashboard":
        run_dashboard()
    elif args.command == "query":
        run_query(args.sql)
    elif args.command == "status":
        show_status()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

from pathlib import Path

# Diretórios do Data Lake (Medallion Architecture)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_STOCKS_DIR = RAW_DIR / "stocks"
RAW_MACRO_DIR = RAW_DIR / "macro"
TRUSTED_DIR = DATA_DIR / "trusted"

# Ativos monitorados na PoC
TICKERS_STOCKS = [
    "PETR4.SA",
    "VALE3.SA",
    "ITUB4.SA",
    "WEGE3.SA",
    "BBAS3.SA",
]

BENCHMARK_TICKER = "^BVSP"
ALL_TICKERS = TICKERS_STOCKS + [BENCHMARK_TICKER]

TICKER_NAMES = {
    "PETR4.SA": "Petrobras (PETR4)",
    "VALE3.SA": "Vale (VALE3)",
    "ITUB4.SA": "Itaú Unibanco (ITUB4)",
    "WEGE3.SA": "WEG (WEGE3)",
    "BBAS3.SA": "Banco do Brasil (BBAS3)",
    "^BVSP": "Ibovespa (IBOV)",
    "SELIC": "Taxa Selic Acumulada",
}

# Séries Temporais do Banco Central do Brasil (SGS)
# Série 11: Taxa Selic diária (% a.d.)
# Série 12: Taxa CDI diária (% a.d.)
# Série 432: Meta Selic (% a.a.)
BCB_SERIES = {
    "selic_diaria": 11,
    "cdi_diaria": 12,
}

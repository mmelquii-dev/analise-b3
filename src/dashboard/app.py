import datetime
import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import duckdb
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import polars as pl
import streamlit as st

from src.config import TRUSTED_DIR


# Configuração da página
st.set_page_config(
    page_title="Big Data Finance | B3 vs Selic & IBOV",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilização CSS Dark Premium
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1e222d 0%, #2a2e39 100%);
        border: 1px solid #363c4e;
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
    }
    .metric-title {
        color: #848e9c;
        font-size: 0.85rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .metric-value {
        font-size: 1.8rem;
        font-weight: 700;
        margin-top: 4px;
        margin-bottom: 2px;
    }
    .metric-delta {
        font-size: 0.85rem;
        font-weight: 500;
    }
    .positive { color: #0ecb81; }
    .negative { color: #f6465d; }
    .neutral { color: #f0b90b; }
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        background-color: #2b313f;
        color: #00bcd4;
        border: 1px solid #00bcd4;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=600)
def load_trusted_data():
    trusted_file = TRUSTED_DIR / "market_benchmark_5y.parquet"
    kpi_file = TRUSTED_DIR / "kpi_metrics.parquet"
    duckdb_file = TRUSTED_DIR / "analytics.duckdb"

    if not trusted_file.exists() or not kpi_file.exists():
        return None, None, None

    df_series = pl.read_parquet(trusted_file)
    df_kpi = pl.read_parquet(kpi_file)
    return df_series, df_kpi, duckdb_file


df_series, df_kpi, duckdb_file = load_trusted_data()

# Header Principal
st.title("📊 Big Data Finance Pipeline")
st.markdown("""
<div style="margin-bottom: 20px;">
    <span class="badge">Modern Data Stack</span>
    <span class="badge" style="color: #4caf50; border-color: #4caf50;">DuckDB + Polars</span>
    <span class="badge" style="color: #ff9800; border-color: #ff9800;">Parquet Lakehouse</span>
    <span class="badge" style="color: #e91e63; border-color: #e91e63;">BACEN SGS + B3</span>
</div>
""", unsafe_allow_html=True)

if df_series is None:
    st.error("⚠️ Os dados da camada TRUSTED ainda não foram gerados!")
    st.info("Execute primeiro a ingestão e o processamento no terminal ou via CLI:")
    st.code("uv run python main.py pipeline", language="bash")
    st.stop()

# Sidebar de Filtros
st.sidebar.header("🔍 Controles do Pipeline")

all_tickers = df_series["ticker"].unique().to_list()
stocks_only = [t for t in all_tickers if t not in ["SELIC", "^BVSP"]]

selected_stocks = st.sidebar.multiselect(
    "Ações da B3:",
    options=stocks_only,
    default=stocks_only,
)

include_selic = st.sidebar.checkbox("Comparar com Taxa Selic", value=True)
include_ibov = st.sidebar.checkbox("Comparar com Ibovespa (^BVSP)", value=True)

selected_tickers = list(selected_stocks)
if include_selic and "SELIC" in all_tickers:
    selected_tickers.append("SELIC")
if include_ibov and "^BVSP" in all_tickers:
    selected_tickers.append("^BVSP")

# Filtro de Período
period_option = st.sidebar.radio(
    "Janela Temporal:",
    options=["1 Ano", "2 Anos", "3 Anos", "5 Anos (Completo)"],
    index=3,
)

max_date = df_series["date"].max()
days_map = {
    "1 Ano": 365,
    "2 Anos": 730,
    "3 Anos": 1095,
    "5 Anos (Completo)": 365 * 5 + 30,
}
filter_start_date = max_date - datetime.timedelta(days=days_map[period_option])

# Filtragem dos dados e rebase da rentabilidade para o período selecionado
filtered_df = df_series.filter(
    (pl.col("ticker").is_in(selected_tickers)) & (pl.col("date") >= filter_start_date)
).sort(["ticker", "date"])

# Rebase para que todos comecem exatamente no zero ou base 100 na data inicial da janela
if len(filtered_df) > 0:
    rebased_df = (
        filtered_df
        .with_columns([
            pl.col("adj_close").first().over("ticker").alias("base_adj_close")
        ])
        .with_columns([
            (((pl.col("adj_close") / pl.col("base_adj_close")) - 1.0) * 100.0).round(2).alias("rebased_return_pct"),
            ((pl.col("adj_close") / pl.col("base_adj_close")) * 100.0).round(2).alias("rebased_index_100"),
        ])
    )
else:
    rebased_df = filtered_df

# Visualização por Abas
tab_analytics, tab_risk, tab_sql, tab_lake = st.tabs([
    "📈 Comparativo de Rentabilidade",
    "🛡️ Risco & Drawdown",
    "⚡ Consulta SQL OLAP (DuckDB)",
    "📁 Arquitetura do Data Lake",
])

# ----------------- ABA 1: ANALYTICS -----------------
with tab_analytics:
    # KPI Ribbon
    col1, col2, col3, col4 = st.columns(4)

    # Melhor Ativo
    best_stock = df_kpi.filter(pl.col("ticker").is_in(stocks_only)).sort("retorno_total_pct", descending=True).head(1)
    if len(best_stock) > 0:
        row = best_stock.to_dicts()[0]
        col1.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">🏆 Campeão de Rentabilidade</div>
            <div class="metric-value positive">+{row['retorno_total_pct']:.1f}%</div>
            <div class="metric-delta">{row['ticker']} ({row['ticker_name']}) | CAGR: {row['cagr_anual_pct']}% a.a.</div>
        </div>
        """, unsafe_allow_html=True)

    # Benchmark Selic
    selic_kpi = df_kpi.filter(pl.col("ticker") == "SELIC")
    if len(selic_kpi) > 0:
        row = selic_kpi.to_dicts()[0]
        col2.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">🏦 Taxa Selic Acumulada</div>
            <div class="metric-value neutral">+{row['retorno_total_pct']:.1f}%</div>
            <div class="metric-delta">Taxa Livre de Risco (CAGR: {row['cagr_anual_pct']}% a.a.)</div>
        </div>
        """, unsafe_allow_html=True)

    # Benchmark Ibovespa
    ibov_kpi = df_kpi.filter(pl.col("ticker") == "^BVSP")
    if len(ibov_kpi) > 0:
        row = ibov_kpi.to_dicts()[0]
        col3.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">🇧🇷 Índice Ibovespa</div>
            <div class="metric-value neutral">+{row['retorno_total_pct']:.1f}%</div>
            <div class="metric-delta">Mercado Amplo (CAGR: {row['cagr_anual_pct']}% a.a.)</div>
        </div>
        """, unsafe_allow_html=True)

    # Menor Drawdown (excluindo Selic)
    safest_stock = df_kpi.filter(pl.col("ticker").is_in(stocks_only)).sort("max_drawdown_pct", descending=True).head(1)
    if len(safest_stock) > 0:
        row = safest_stock.to_dicts()[0]
        col4.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">🛡️ Menor Queda Máxima</div>
            <div class="metric-value negative">{row['max_drawdown_pct']:.1f}%</div>
            <div class="metric-delta">{row['ticker']} ({row['ticker_name']})</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("### 📈 Curva de Rentabilidade Acumulada no Período")

    # Opção de Escala
    chart_mode = st.radio(
        "Métrica do Gráfico:",
        options=["Rentabilidade (%)", "Índice Base 100"],
        horizontal=True,
    )
    y_col = "rebased_return_pct" if chart_mode == "Rentabilidade (%)" else "rebased_index_100"
    y_label = "Rentabilidade Acumulada (%)" if chart_mode == "Rentabilidade (%)" else "Valor Normalizado (Base 100)"

    # Plotly Line Chart
    df_plot = rebased_df.to_pandas()
    color_discrete_map = {
        "SELIC": "#f0b90b",    # Dourado
        "^BVSP": "#00bcd4",    # Ciano
        "PETR4.SA": "#0ecb81", # Verde
        "VALE3.SA": "#9c27b0", # Roxo
        "ITUB4.SA": "#ff9800", # Laranja
        "WEGE3.SA": "#2196f3", # Azul
        "BBAS3.SA": "#e91e63", # Rosa
    }

    fig = px.line(
        df_plot,
        x="date",
        y=y_col,
        color="ticker",
        color_discrete_map=color_discrete_map,
        labels={"date": "Data", y_col: y_label, "ticker": "Ativo"},
        title=f"Evolução Comparativa ({period_option})",
    )

    # Estiliza o benchmark Selic com linha pontilhada mais grossa para contraste
    for trace in fig.data:
        if trace.name == "SELIC":
            trace.line.width = 3
            trace.line.dash = "dash"
        elif trace.name == "^BVSP":
            trace.line.width = 2.5
            trace.line.dash = "dot"
        else:
            trace.line.width = 2

    fig.update_layout(
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=50, b=20),
        xaxis=dict(showgrid=True, gridcolor="#2a2e39"),
        yaxis=dict(showgrid=True, gridcolor="#2a2e39", ticksuffix="%" if chart_mode == "Rentabilidade (%)" else ""),
    )

    st.plotly_chart(fig, use_container_width=True)

    # Tabela com Indicadores Completos
    st.markdown("### 📋 Tabela Analítica de Indicadores Financeiros (5 Anos)")
    kpi_display = df_kpi.filter(pl.col("ticker").is_in(selected_tickers)).to_pandas()
    st.dataframe(
        kpi_display.style.format({
            "retorno_total_pct": "{:+.2f}%",
            "cagr_anual_pct": "{:+.2f}%",
            "volatilidade_anual_pct": "{:.2f}%",
            "max_drawdown_pct": "{:.2f}%",
            "sharpe_ratio": "{:.2f}",
        }).background_gradient(subset=["retorno_total_pct"], cmap="Greens"),
        use_container_width=True,
    )


# ----------------- ABA 2: RISCO & DRAWDOWN -----------------
with tab_risk:
    st.markdown("### 🌊 Análise de Drawdown (Perda em Relação ao Topo)")

    # Calcula drawdown diário para cada ativo selecionado
    drawdown_dfs = []
    for ticker in selected_tickers:
        sub = rebased_df.filter(pl.col("ticker") == ticker).sort("date").to_pandas()
        if len(sub) == 0:
            continue
        cum_max = sub["adj_close"].cummax()
        sub["drawdown_pct"] = ((sub["adj_close"] - cum_max) / cum_max) * 100.0
        drawdown_dfs.append(sub)

    if drawdown_dfs:
        dd_combined = pl.concat([pl.from_pandas(df) for df in drawdown_dfs]).to_pandas()

        fig_dd = px.line(
            dd_combined,
            x="date",
            y="drawdown_pct",
            color="ticker",
            color_discrete_map=color_discrete_map,
            labels={"date": "Data", "drawdown_pct": "Drawdown (%)", "ticker": "Ativo"},
            title="Queda Máxima ao Longo do Tempo (Underwater Chart)",
        )
        fig_dd.update_layout(
            template="plotly_dark",
            hovermode="x unified",
            yaxis=dict(ticksuffix="%", range=[-60, 5], gridcolor="#2a2e39"),
            xaxis=dict(gridcolor="#2a2e39"),
            margin=dict(l=20, r=20, t=50, b=20),
        )
        st.plotly_chart(fig_dd, use_container_width=True)

    # Matriz de Correlação
    st.markdown("### 🧩 Matriz de Correlação dos Retornos Diários")
    
    # Pivot de retornos diários
    pivot_df = (
        rebased_df
        .pivot(on="ticker", index="date", values="daily_return")
        .sort("date")
        .drop_nulls()
        .to_pandas()
        .set_index("date")
    )

    if len(pivot_df) > 1:
        corr_matrix = pivot_df.corr().round(2)
        fig_corr = px.imshow(
            corr_matrix,
            text_auto=True,
            aspect="auto",
            color_continuous_scale="RdBu_r",
            range_color=[-1, 1],
            title="Correlação Linear de Pearson",
        )
        fig_corr.update_layout(template="plotly_dark", margin=dict(l=20, r=20, t=50, b=20))
        st.plotly_chart(fig_corr, use_container_width=True)


# ----------------- ABA 3: DUCKDB SQL OLAP -----------------
with tab_sql:
    st.markdown("### ⚡ Consulta SQL Analítica Direta (DuckDB OLAP)")
    st.markdown("Você pode escrever queries SQL diretamente sobre as tabelas analíticas geradas pelo pipeline.")

    sample_query = """SELECT 
    ticker,
    ticker_name,
    MIN(date) as data_inicial,
    MAX(date) as data_final,
    ROUND(MAX(cumulative_return_pct), 2) as max_retorno_pct,
    ROUND(AVG(daily_return) * 100, 3) as media_diaria_pct
FROM market_benchmark
GROUP BY ticker, ticker_name
ORDER BY max_retorno_pct DESC;"""

    query = st.text_area("Digite sua consulta SQL:", value=sample_query, height=140)

    if st.button("Executar Query", type="primary"):
        try:
            con = duckdb.connect(str(duckdb_file), read_only=True)
            res = con.execute(query).df()
            con.close()
            st.success(f"Query executada com sucesso! ({len(res)} linhas retornadas)")
            st.dataframe(res, use_container_width=True)
        except Exception as e:
            st.error(f"Erro ao executar SQL: {e}")


# ----------------- ABA 4: DATA LAKE LAKEHOUSE -----------------
with tab_lake:
    st.markdown("### 🗄️ Estrutura do Data Lake (Medallion Architecture)")
    st.markdown("Os dados são organizados no padrão de **Medallion Architecture** em formato colunar Parquet compactado com Zstandard:")

    col_raw, col_trusted = st.columns(2)

    with col_raw:
        st.markdown("#### 🥉 Camada RAW (Bruto)")
        st.markdown("Dados puros salvos diretamente das fontes (yfinance e Banco Central SGS):")
        raw_files = list(Path("data/raw").glob("**/*.parquet"))
        for rf in raw_files:
            size_kb = rf.stat().st_size / 1024
            rows = len(pl.read_parquet(rf))
            st.markdown(f"- 📄 `{rf.relative_to(Path('.'))}`: **{size_kb:.1f} KB** ({rows:,} registros)")

    with col_trusted:
        st.markdown("#### 🥈 Camada TRUSTED (Transformado & Enriquecido)")
        st.markdown("Dados limpos, normalizados, com rentabilidade acumulada e métricas prontas:")
        trusted_files = list(Path("data/trusted").glob("**/*"))
        for tf in trusted_files:
            size_kb = tf.stat().st_size / 1024
            st.markdown(f"- 📁 `{tf.relative_to(Path('.'))}`: **{size_kb:.1f} KB**")

    st.markdown("---")
    st.markdown("#### 🔍 Schema da Tabela Unificada `market_benchmark_5y.parquet`")
    schema_info = pl.read_parquet(TRUSTED_DIR / "market_benchmark_5y.parquet").schema
    schema_df = pl.DataFrame({
        "Coluna": list(schema_info.keys()),
        "Tipo de Dado": [str(t) for t in schema_info.values()],
    })
    st.table(schema_df)

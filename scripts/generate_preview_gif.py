import datetime
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from PIL import Image
import polars as pl

# Caminhos
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "trusted" / "market_benchmark_5y.parquet"
OUTPUT_DIR = BASE_DIR / "docs" / "assets"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_GIF = OUTPUT_DIR / "dashboard_preview.gif"
OUTPUT_PNG = OUTPUT_DIR / "dashboard_preview.png"

# Cores modernas tipo TradingView / Dark Theme
COLORS = {
    "PETR4.SA": "#00E676",  # Verde neon
    "ITUB4.SA": "#FF9100",  # Laranja
    "BBAS3.SA": "#FF4081",  # Rosa
    "SELIC": "#FFD700",     # Dourado
    "^BVSP": "#00E5FF",     # Ciano
    "WEGE3.SA": "#2979FF",  # Azul
    "VALE3.SA": "#B388FF",  # Roxo
}

LABELS = {
    "PETR4.SA": "PETR4 (+631.7%)",
    "ITUB4.SA": "ITUB4 (+171.4%)",
    "BBAS3.SA": "BBAS3 (+143.6%)",
    "SELIC": "SELIC (+81.8%)",
    "^BVSP": "IBOV (+79.9%)",
    "WEGE3.SA": "WEGE3 (+46.3%)",
    "VALE3.SA": "VALE3 (+20.5%)",
}

def generate_animated_gif():
    print("Gerando GIF animado do pipeline financeiro...")
    df = pl.read_parquet(DATA_PATH).sort(["date", "ticker"])
    
    unique_dates = df.select("date").unique().sort("date")["date"].to_list()
    total_dates = len(unique_dates)

    # 45 frames para animação suave
    num_frames = 45
    step = total_dates // num_frames
    
    frame_indices = [min((i + 1) * step, total_dates) for i in range(num_frames)]
    if frame_indices[-1] < total_dates:
        frame_indices.append(total_dates)

    # Coletar dados de cada série
    series_data = {}
    for ticker in COLORS.keys():
        sub = df.filter(pl.col("ticker") == ticker).sort("date")
        dates = [datetime.datetime.combine(d, datetime.time()) for d in sub["date"].to_list()]
        vals = sub["cumulative_return_pct"].to_list()
        series_data[ticker] = (dates, vals)

    all_dates = [datetime.datetime.combine(d, datetime.time()) for d in unique_dates]
    min_date = all_dates[0]
    max_date = all_dates[-1]

    frames = []

    # Configuração de estilo escuro
    plt.style.use("dark_background")

    for f_idx, cutoff_idx in enumerate(frame_indices):
        fig, ax = plt.subplots(figsize=(12, 6.2), dpi=100)
        fig.patch.set_facecolor("#0D1117")
        ax.set_facecolor("#161B22")

        # Título e Subtítulo
        fig.text(0.12, 0.94, "Big Data Finance Pipeline | Rentabilidade Acumulada (5 Anos)", 
                 fontsize=14, fontweight="bold", color="#F0F6FC")
        fig.text(0.12, 0.90, "Ativos da B3 vs Taxa Selic & Ibovespa • Processado com DuckDB & Polars", 
                 fontsize=10, color="#8B949E")

        # Plotar cada curva até o corte atual
        for ticker, color in COLORS.items():
            if ticker not in series_data:
                continue
            dates, vals = series_data[ticker]
            cur_dates = dates[:cutoff_idx]
            cur_vals = vals[:cutoff_idx]
            
            if not cur_dates:
                continue

            lw = 3.0 if ticker in ["SELIC", "PETR4.SA", "^BVSP"] else 2.0
            ls = "--" if ticker == "SELIC" else (":" if ticker == "^BVSP" else "-")
            alpha = 1.0 if ticker in ["SELIC", "PETR4.SA", "^BVSP"] else 0.85

            ax.plot(cur_dates, cur_vals, color=color, linewidth=lw, linestyle=ls, 
                    alpha=alpha, label=LABELS.get(ticker, ticker))
            
            # Ponto brilhante na ponta da curva
            if len(cur_vals) > 0:
                ax.scatter(cur_dates[-1], cur_vals[-1], color=color, s=25, zorder=5)

        # Configurações dos eixos
        ax.set_xlim(min_date, max_date)
        ax.set_ylim(-50, 680)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
        ax.xaxis.set_major_locator(mdates.YearLocator())

        ax.grid(True, linestyle="--", alpha=0.15, color="#8B949E")
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color("#30363D")
        ax.spines["bottom"].set_color("#30363D")
        ax.tick_params(colors="#8B949E", labelsize=9)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:+.0f}%"))

        # Legenda no topo
        ax.legend(loc="upper left", bbox_to_anchor=(0.01, 0.98), ncol=4, 
                  fontsize=8.5, framealpha=0.8, facecolor="#0D1117", edgecolor="#30363D")

        # Salvar frame na memória
        fig.tight_layout(rect=[0.05, 0.05, 0.95, 0.88])
        fig.canvas.draw()
        img = Image.frombuffer("RGBA", fig.canvas.get_width_height(), fig.canvas.buffer_rgba())
        frames.append(img.convert("P", palette=Image.ADAPTIVE))
        
        # Salva o último frame também como imagem estática PNG de alta resolução
        if f_idx == len(frame_indices) - 1:
            fig.savefig(OUTPUT_PNG, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")

        plt.close(fig)

    # Duplicar o último frame para pausar por 2.5 segundos no final
    for _ in range(15):
        frames.append(frames[-1])

    # Salva o GIF otimizado
    frames[0].save(
        OUTPUT_GIF,
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        optimize=True,
    )
    print(f"✔ GIF gerado com sucesso: {OUTPUT_GIF} ({OUTPUT_GIF.stat().st_size / 1024:.1f} KB)")
    print(f"✔ PNG estático gerado: {OUTPUT_PNG} ({OUTPUT_PNG.stat().st_size / 1024:.1f} KB)")

if __name__ == "__main__":
    generate_animated_gif()

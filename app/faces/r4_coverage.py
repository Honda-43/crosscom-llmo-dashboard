"""R4 獲得マップ — prompt × model の言及日数ヒートグリッド(Phase 5 §1)."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import board
import common
import data_source

board.face_header("R4", "獲得マップ", "直近7日でどの組み合わせが取れているか")

if not data_source.sheets_available():
    data_source.missing_credentials_notice()
    st.stop()

obs = board.observations()
if obs.empty:
    common.empty_state("llm_observations にデータがありません。")
    st.stop()

end = board.latest_date(obs)
recent = obs[obs["date"] > end - pd.Timedelta(days=board.WINDOW_DAYS)]
grid = (recent.groupby(["prompt_id", "model"])
        .agg(mentioned=("mention_bool", "sum"), observed=("mention_bool", "size"))
        .reset_index())

prompts = sorted(grid["prompt_id"].unique())
models = sorted(grid["model"].unique())
lookup = {(r.prompt_id, r.model): (int(r.mentioned), int(r.observed))
          for r in grid.itertuples()}

z, text, hover, zero_cells = [], [], [], []
for prompt_id in prompts:
    z_row, t_row, h_row = [], [], []
    for model in models:
        mentioned, observed = lookup.get((prompt_id, model), (None, 0))
        z_row.append(mentioned)
        t_row.append("—" if mentioned is None else str(mentioned))
        h_row.append(
            f"{prompt_id} × {model}<br>言及 {mentioned} 日 / 観測 {observed} 日"
            if mentioned is not None else f"{prompt_id} × {model}<br>観測なし")
        # E-1は必ず言及されるので「取れていない組み合わせ」から除く
        if mentioned == 0 and prompt_id != "E-1":
            zero_cells.append(f"{prompt_id}×{model}")
    z.append(z_row)
    text.append(t_row)
    hover.append(h_row)

figure = go.Figure(go.Heatmap(
    z=z, x=models, y=prompts, zmin=0, zmax=board.WINDOW_DAYS,
    colorscale=common.SEQUENTIAL, xgap=3, ygap=3,
    text=text, texttemplate="%{text}", textfont=dict(size=15),
    customdata=hover, hovertemplate="%{customdata}<extra></extra>",
    colorbar=dict(title=dict(text="言及日数", side="right"),
                  tickvals=list(range(0, board.WINDOW_DAYS + 1)),
                  thickness=14, len=0.9),
))
if "E-1" in prompts:
    row = prompts.index("E-1")
    figure.add_shape(type="rect", x0=-0.5, x1=len(models) - 0.5,
                     y0=row - 0.5, y1=row + 0.5,
                     line=dict(color=common.INK, width=2.5), fillcolor="rgba(0,0,0,0)")
figure.update_layout(
    height=max(280, 46 * len(prompts) + 100), margin=dict(l=10, r=10, t=10, b=40),
    xaxis=dict(title="model", tickfont=dict(color=common.INK)),
    yaxis=dict(title=None, autorange="reversed", tickfont=dict(color=common.INK)),
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(figure, width="stretch")
st.caption(
    "セルの数字と濃さは直近7日で mention=TRUE だった日数(0日=白 〜 7日=濃)。"
    "**枠線のE-1**は必ず言及されるため他と意味が異なる。"
    "個別の推移は「詳細:プロンプト」で追える。"
)

label = "、".join(zero_cells[:5])
if len(zero_cells) > 5:
    label += f" ほか{len(zero_cells) - 5}件"
board.verdict_panel("R4", board.build_context(
    "R4",
    zero_cells=len(zero_cells), zero_cells_label=label,
))

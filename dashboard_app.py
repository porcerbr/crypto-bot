from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Forex Signal Desk", layout="wide", page_icon="📈")
st.title("Forex Signal Desk")

signals_path = Path("data/signals.csv")
metrics_path = Path("reports/backtest_metrics.json")
trades_path = Path("reports/backtest_trades.csv")

col1, col2, col3, col4 = st.columns(4)

signals_df = pd.read_csv(signals_path) if signals_path.exists() else pd.DataFrame()
if not signals_df.empty:
    latest = signals_df.iloc[-1]
    col1.metric("Último ativo", latest.get("symbol", "-"))
    col2.metric("Último lado", latest.get("side", "-"))
    col3.metric("Score", f"{float(latest.get('score', 0)):.1f}")
    col4.metric("Confiança", f"{float(latest.get('confidence', 0)):.0%}")
else:
    col1.metric("Último ativo", "-")
    col2.metric("Último lado", "-")
    col3.metric("Score", "-")
    col4.metric("Confiança", "-")

st.subheader("Sinais")
st.dataframe(signals_df.tail(50), use_container_width=True)

if not signals_df.empty and "created_at" in signals_df.columns:
    signals_df["created_at"] = pd.to_datetime(signals_df["created_at"], errors="coerce")
    chart = px.line(signals_df.dropna(subset=["created_at"]), x="created_at", y="score", color="symbol", title="Score ao longo do tempo")
    st.plotly_chart(chart, use_container_width=True)

if metrics_path.exists():
    st.subheader("Métricas do backtest")
    st.json(pd.read_json(metrics_path, typ="series").to_dict())

if trades_path.exists():
    st.subheader("Trades do backtest")
    st.dataframe(pd.read_csv(trades_path).tail(50), use_container_width=True)

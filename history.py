"""
storage/history.py — Histórico completo em SQLite
Persiste todos os sinais, bloqueios e métricas de desempenho.
"""

import sqlite3
import json
from datetime import datetime, date, timedelta
from pathlib import Path
from loguru import logger

from core.config import settings


class HistoryManager:
    """
    Banco de dados local com SQLite.
    Tabelas:
      signals  — todos os sinais gerados (abertos e fechados)
      blocked  — operações bloqueadas pelo risk manager
      cycles   — registro de cada ciclo do bot
    """

    def __init__(self):
        self._db_path = Path(settings.DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

    def initialize_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT,
                    symbol TEXT,
                    direction TEXT,
                    entry_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    score REAL,
                    risk_reward REAL,
                    status TEXT,
                    pnl_pct REAL,
                    market_regime TEXT,
                    timeframe TEXT,
                    reasons TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS blocked (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    symbol TEXT,
                    direction TEXT,
                    score REAL,
                    block_reason TEXT,
                    market_regime TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    price REAL,
                    rsi REAL,
                    macd_hist REAL,
                    adx REAL,
                    score REAL,
                    direction TEXT,
                    regime TEXT
                )
            """)
        logger.info(f"Banco de dados inicializado: {self._db_path}")

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def record_signal(self, signal):
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT OR REPLACE INTO signals VALUES
                    (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        signal.id, signal.timestamp, signal.symbol,
                        signal.direction, signal.entry_price, signal.stop_loss,
                        signal.take_profit, signal.score, signal.risk_reward,
                        signal.status, signal.pnl_pct, signal.market_regime,
                        signal.timeframe, json.dumps(signal.reasons),
                    ),
                )
        except Exception as exc:
            logger.error(f"Falha ao registrar sinal: {exc}")

    def record_blocked(self, analysis, risk_result):
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO blocked
                    (timestamp,symbol,direction,score,block_reason,market_regime)
                    VALUES (?,?,?,?,?,?)""",
                    (
                        datetime.utcnow().isoformat(),
                        analysis.symbol, analysis.direction,
                        analysis.score, risk_result.reason,
                        analysis.market_regime,
                    ),
                )
        except Exception as exc:
            logger.error(f"Falha ao registrar bloqueio: {exc}")

    def record_cycle(self, analysis, price: float):
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO cycles
                    (timestamp,price,rsi,macd_hist,adx,score,direction,regime)
                    VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        datetime.utcnow().isoformat(), price,
                        analysis.rsi, analysis.macd_hist,
                        analysis.adx, analysis.score,
                        analysis.direction, analysis.market_regime,
                    ),
                )
        except Exception as exc:
            logger.error(f"Falha ao registrar ciclo: {exc}")

    def get_performance(self) -> dict:
        """Retorna métricas de desempenho para a dashboard."""
        try:
            with self._conn() as conn:
                conn.row_factory = sqlite3.Row

                # Totais gerais
                rows = conn.execute(
                    "SELECT status, COUNT(*) as cnt, AVG(pnl_pct) as avg_pnl "
                    "FROM signals GROUP BY status"
                ).fetchall()

                totals = {"total": 0, "wins": 0, "losses": 0, "open": 0,
                          "avg_pnl": 0.0, "win_rate": 0.0}
                for r in rows:
                    totals["total"] += r["cnt"]
                    if r["status"] == "hit_tp":
                        totals["wins"] = r["cnt"]
                    elif r["status"] == "hit_sl":
                        totals["losses"] = r["cnt"]
                    elif r["status"] == "open":
                        totals["open"] = r["cnt"]

                closed = totals["wins"] + totals["losses"]
                if closed > 0:
                    totals["win_rate"] = round(totals["wins"] / closed * 100, 1)

                # Período diário
                today = date.today().isoformat()
                day_row = conn.execute(
                    "SELECT COUNT(*) as cnt, SUM(pnl_pct) as pnl "
                    "FROM signals WHERE timestamp LIKE ? AND status != 'open'",
                    (f"{today}%",),
                ).fetchone()
                totals["today_trades"] = day_row["cnt"] or 0
                totals["today_pnl"] = round(day_row["pnl"] or 0, 2)

                # Período semanal
                week_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
                week_row = conn.execute(
                    "SELECT COUNT(*) as cnt, SUM(pnl_pct) as pnl "
                    "FROM signals WHERE timestamp >= ? AND status != 'open'",
                    (week_ago,),
                ).fetchone()
                totals["week_trades"] = week_row["cnt"] or 0
                totals["week_pnl"] = round(week_row["pnl"] or 0, 2)

                # Período mensal
                month_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
                month_row = conn.execute(
                    "SELECT COUNT(*) as cnt, SUM(pnl_pct) as pnl "
                    "FROM signals WHERE timestamp >= ? AND status != 'open'",
                    (month_ago,),
                ).fetchone()
                totals["month_trades"] = month_row["cnt"] or 0
                totals["month_pnl"] = round(month_row["pnl"] or 0, 2)

                # Últimos sinais
                recent = conn.execute(
                    "SELECT * FROM signals ORDER BY timestamp DESC LIMIT 20"
                ).fetchall()
                totals["recent_signals"] = [dict(r) for r in recent]

                return totals
        except Exception as exc:
            logger.error(f"Erro ao calcular performance: {exc}")
            return {}

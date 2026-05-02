"""Persistência de trades e métricas em SQLite.

Usa SQLite por ser serverless, confiável e perfeito para
ambientes como Railway onde não queremos gerenciar
banco de dados separado para um bot single-instance.
"""
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from config import get_settings

logger = logging.getLogger("TradeDatabase")


class TradeDatabase:
    """Banco de dados SQLite thread-safe para o bot."""

    def __init__(self):
        self.settings = get_settings()
        self.db_path = Path(self.settings.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Retorna conexão thread-local."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        """Cria tabelas se não existirem."""
        with self._transaction() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    size REAL NOT NULL,
                    score INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    pnl REAL DEFAULT 0,
                    exit_price REAL,
                    exit_time TEXT,
                    metadata TEXT,
                    simulation INTEGER DEFAULT 1
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    total_trades INTEGER DEFAULT 0,
                    win_count INTEGER DEFAULT 0,
                    loss_count INTEGER DEFAULT 0,
                    daily_pnl REAL DEFAULT 0,
                    weekly_pnl REAL DEFAULT 0,
                    monthly_pnl REAL DEFAULT 0,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO metrics (id, updated_at) VALUES (1, ?)
            """, (datetime.now(timezone.utc).isoformat(),))

    @contextmanager
    def _transaction(self):
        """Context manager para transações."""
        conn = self._get_conn()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def save_trade(self, trade: Dict[str, Any]):
        """Persiste um trade no banco."""
        with self._transaction() as conn:
            conn.execute("""
                INSERT INTO trades 
                (id, timestamp, symbol, direction, entry_price, size, score, status, pnl, exit_price, exit_time, metadata, simulation)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade["id"],
                trade["timestamp"],
                trade.get("symbol", ""),
                trade["direction"],
                trade["entry_price"],
                trade["size"],
                trade["score"],
                trade["status"],
                trade.get("pnl", 0),
                trade.get("exit_price"),
                trade.get("exit_time"),
                json.dumps(trade.get("metadata", {})),
                1 if trade.get("simulation", True) else 0,
            ))
        logger.info(f"Trade salvo: {trade['id']}")

    def get_open_trades(self) -> List[Dict[str, Any]]:
        """Retorna trades com status OPEN."""
        with self._transaction() as conn:
            cursor = conn.execute("SELECT * FROM trades WHERE status = 'OPEN' ORDER BY timestamp DESC")
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retorna trades recentes."""
        with self._transaction() as conn:
            cursor = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def update_metrics(self, metrics: Dict[str, Any]):
        """Atualiza métricas agregadas."""
        with self._transaction() as conn:
            conn.execute("""
                UPDATE metrics SET
                    total_trades = ?,
                    win_count = ?,
                    loss_count = ?,
                    daily_pnl = ?,
                    weekly_pnl = ?,
                    monthly_pnl = ?,
                    updated_at = ?
                WHERE id = 1
            """, (
                metrics.get("total_trades", 0),
                metrics.get("win_count", 0),
                metrics.get("loss_count", 0),
                metrics.get("daily_pnl", 0.0),
                metrics.get("weekly_pnl", 0.0),
                metrics.get("monthly_pnl", 0.0),
                datetime.now(timezone.utc).isoformat(),
            ))

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Retorna métricas de performance."""
        with self._transaction() as conn:
            cursor = conn.execute("SELECT * FROM metrics WHERE id = 1")
            row = cursor.fetchone()
        return dict(row) if row else {}

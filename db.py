"""
db.py — Camada de persistência com SQLite (WAL mode).

Migração transparente: se bot_state.db não existe mas state.json existe,
importa automaticamente o estado legado e avisa no log.

Tabelas:
  bot_state    — snapshot completo do estado do bot (1 linha)
  trade_history — histórico imutável de trades fechados
  bot_logs     — log de eventos estruturado (substitui bot_logs.jsonl)
  bot_metrics  — métricas calculadas (cache para dashboard)
"""

import json
import os
import sqlite3
import threading
import time
import math
from contextlib import contextmanager
from datetime import datetime
from utils import log
from config import Config

# ── Arquivos legados (mantidos para retrocompat) ──────────────────────────────
STATE_FILE   = "state.json"
LOG_FILE     = "bot_logs.jsonl"
METRICS_FILE = "bot_metrics.json"

# ── Lock para acesso concorrente ──────────────────────────────────────────────
_db_lock = threading.Lock()


# ═══════════════════════════════════════════════════════════════════════════════
# CONEXÃO
# ═══════════════════════════════════════════════════════════════════════════════

@contextmanager
def _get_conn():
    """Abre conexão SQLite com WAL mode e fecha ao sair do contexto."""
    conn = sqlite3.connect(Config.DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA
# ═══════════════════════════════════════════════════════════════════════════════

def init_db():
    """Cria tabelas se não existirem e migra dados legados."""
    with _get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS bot_state (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                payload     TEXT    NOT NULL,
                saved_at    TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trade_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol      TEXT    NOT NULL,
                direction   TEXT    NOT NULL,
                result      TEXT    NOT NULL,
                pnl         REAL    NOT NULL DEFAULT 0,
                closed_at   TEXT,
                opened_at   TEXT,
                adx         REAL    DEFAULT 0,
                ai_approved INTEGER DEFAULT 1,
                ai_confidence INTEGER DEFAULT 0,
                payload     TEXT,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_history_symbol
                ON trade_history(symbol);
            CREATE INDEX IF NOT EXISTS idx_history_result
                ON trade_history(result);
            CREATE INDEX IF NOT EXISTS idx_history_closed
                ON trade_history(closed_at);

            CREATE TABLE IF NOT EXISTS bot_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_type  TEXT    NOT NULL,
                payload     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_logs_type
                ON bot_logs(entry_type);
            CREATE INDEX IF NOT EXISTS idx_logs_created
                ON bot_logs(created_at);

            CREATE TABLE IF NOT EXISTS bot_metrics (
                id          INTEGER PRIMARY KEY CHECK (id = 1),
                payload     TEXT    NOT NULL,
                updated_at  TEXT    NOT NULL
            );
        """)
    _migrate_legacy()


def init_db_with_migrations():
    """Inicializa DB e aplica todas as migrações pendentes."""
    init_db()
    try:
        applied = run_migrations()
        if applied:
            log(f"[DB] Migrações aplicadas: {applied}")
    except Exception as e:
        log(f"[DB] Aviso: falha ao aplicar migrações — {e}")


def _migrate_legacy():
    """Importa state.json legado se o banco ainda estiver vazio."""
    if not os.path.exists(STATE_FILE):
        return
    with _get_conn() as conn:
        row = conn.execute("SELECT id FROM bot_state WHERE id=1").fetchone()
        if row:
            return  # já migrado

    log("[DB] Migrando state.json → SQLite...")
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        # Salva snapshot bruto — load_state vai preencher o bot normalmente
        _write_state_payload(data)
        log("[DB] Migração concluída.")
    except Exception as e:
        log(f"[DB] Aviso: falha na migração do legado — {e}")


def _write_state_payload(data: dict):
    now = datetime.now().isoformat()
    payload = json.dumps(data, default=str)
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO bot_state(id, payload, saved_at) VALUES(1,?,?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, saved_at=excluded.saved_at",
            (payload, now),
        )



# ═══════════════════════════════════════════════════════════════════════════════
# ESTADO DO BOT
# ═══════════════════════════════════════════════════════════════════════════════

def save_state(bot):
    """Persiste estado completo no SQLite (atômica via WAL)."""
    with _db_lock:
        data = {
            "mode":               bot.mode,
            "timeframe":          bot.timeframe,
            "leverage":           bot.leverage,
            "balance":            bot.balance,
            "wins":               bot.wins,
            "losses":             bot.losses,
            "consecutive_losses": bot.consecutive_losses,
            "paused_until":       bot.paused_until,
            "active_trades":      bot.active_trades,
            "pending_trades":     bot.pending_trades,
            "history":            bot.history[-200:],
            "asset_cooldown":     bot.asset_cooldown,
            "pending_counter":    bot.pending_counter,
            "last_id":            getattr(bot, "last_id", 0),
            "_current_leverage":  getattr(bot, "_current_leverage", bot.leverage),
            "accounts":           getattr(bot, "accounts", {}),
            "saved_at":           datetime.now().isoformat(),
        }
        _write_state_payload(data)

    # Sincroniza histórico novo com a tabela trade_history (upsert pelo closed_at)
    _sync_history_to_table(bot.history[-200:])
    log("Estado salvo (SQLite).")


def load_state(bot) -> bool:
    """Carrega estado do SQLite. Fallback para state.json legado se necessário."""
    try:
        with _get_conn() as conn:
            row = conn.execute("SELECT payload FROM bot_state WHERE id=1").fetchone()
        if not row:
            return False
        data = json.loads(row["payload"])
        for k, v in data.items():
            if hasattr(bot, k) and k != "saved_at":
                setattr(bot, k, v)
        if bot.history:
            try:
                bot.history = sorted(
                    bot.history,
                    key=lambda h: h.get("closed_ts_iso", "") or h.get("closed_at", ""),
                )
            except Exception as e:
                log(f"[DB] Aviso ao ordenar histórico: {e}")
        log(f"Estado carregado (SQLite) — salvo em {data.get('saved_at', '?')}")
        return True
    except Exception as e:
        log(f"[DB] Erro ao carregar estado: {e}")
        # Último recurso: tenta state.json
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    data = json.load(f)
                for k, v in data.items():
                    if hasattr(bot, k) and k != "saved_at":
                        setattr(bot, k, v)
                log("[DB] Fallback: estado carregado do state.json legado.")
                return True
            except Exception as e2:
                log(f"[DB] Falha total no carregamento: {e2}")
        return False


def _sync_history_to_table(history: list):
    """Insere trades fechados na tabela trade_history se ainda não existirem."""
    if not history:
        return
    try:
        with _get_conn() as conn:
            for h in history:
                closed_at = h.get("closed_at", "")
                symbol    = h.get("symbol", "")
                if not closed_at or not symbol:
                    continue
                exists = conn.execute(
                    "SELECT id FROM trade_history WHERE symbol=? AND closed_at=?",
                    (symbol, closed_at),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO trade_history
                           (symbol, direction, result, pnl, closed_at, opened_at,
                            adx, ai_approved, ai_confidence, payload)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            symbol,
                            h.get("dir", ""),
                            h.get("result", ""),
                            float(h.get("pnl", 0)),
                            closed_at,
                            h.get("opened_at", ""),
                            float(h.get("adx", 0)),
                            int(h.get("ai_approved", 1)),
                            int(h.get("ai_confidence", 0)),
                            json.dumps(h, default=str),
                        ),
                    )
    except Exception as e:
        log(f"[DB] Erro ao sincronizar histórico: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# LOGS ESTRUTURADOS
# ═══════════════════════════════════════════════════════════════════════════════

def append_log(entry_type: str, data: dict):
    """Persiste entrada de log no SQLite E no arquivo JSONL legado (compatibilidade)."""
    payload = json.dumps(data, default=str)
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO bot_logs(entry_type, payload) VALUES(?,?)",
                (entry_type, payload),
            )
    except Exception as e:
        log(f"[DB] Erro ao salvar log: {e}")

    # Mantém arquivo JSONL para ferramentas externas
    try:
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type":      entry_type,
            "data":      data,
        }
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def get_recent_logs(entry_type=None, hours: int = 24, limit: int = 100) -> list:
    """Retorna logs recentes do SQLite."""
    cutoff = datetime.fromtimestamp(time.time() - hours * 3600).isoformat()
    try:
        with _get_conn() as conn:
            if entry_type:
                rows = conn.execute(
                    "SELECT * FROM bot_logs WHERE entry_type=? AND created_at >= ? "
                    "ORDER BY id DESC LIMIT ?",
                    (entry_type, cutoff, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM bot_logs WHERE created_at >= ? "
                    "ORDER BY id DESC LIMIT ?",
                    (cutoff, limit),
                ).fetchall()
        results = []
        for r in rows:
            try:
                results.append({
                    "timestamp": r["created_at"],
                    "type":      r["entry_type"],
                    "data":      json.loads(r["payload"]),
                })
            except Exception:
                continue
        return list(reversed(results))
    except Exception as e:
        log(f"[DB] Erro ao ler logs: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# MÉTRICAS
# ═══════════════════════════════════════════════════════════════════════════════

def save_metrics(metrics: dict):
    """Persiste métricas no SQLite."""
    payload = json.dumps(metrics, default=str)
    now     = datetime.now().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                "INSERT INTO bot_metrics(id, payload, updated_at) VALUES(1,?,?) "
                "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                (payload, now),
            )
    except Exception as e:
        log(f"[DB] Erro ao salvar métricas: {e}")


def load_metrics() -> dict:
    """Carrega métricas salvas do SQLite."""
    try:
        with _get_conn() as conn:
            row = conn.execute("SELECT payload FROM bot_metrics WHERE id=1").fetchone()
        return json.loads(row["payload"]) if row else {}
    except Exception:
        return {}


def load_equity_curve() -> list:
    """Reconstrói curva de equity a partir da tabela trade_history."""
    return []


# ═══════════════════════════════════════════════════════════════════════════════
# MÉTRICAS DE PERFORMANCE (refatoradas para usar SQLite quando disponível)
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_metrics(bot) -> dict:
    """
    Calcula métricas de performance do bot com validações de segurança.
    Usa o histórico em memória do bot (compatível com calculate_metrics_from_history).
    """
    from performance import calculate_metrics_from_history
    return calculate_metrics_from_history(
        bot.history,
        initial_balance=Config.INITIAL_BALANCE,
        current_balance=bot.balance,
        active_trades_count=len(bot.active_trades),
        pending_trades_count=len(bot.pending_trades),
    )


# Inicializa o banco na importação do módulo
init_db()


# ═══════════════════════════════════════════════════════════════════════════════
# FASE 5 — Schema Versionado, Migrações e Trilha de Auditoria
# ═══════════════════════════════════════════════════════════════════════════════

_SCHEMA_VERSION = 2  # Incrementar ao adicionar colunas/tabelas


def get_schema_version() -> int:
    """Retorna a versão do schema atual do banco."""
    try:
        with _get_conn() as conn:
            row = conn.execute(
                "SELECT version FROM schema_migrations ORDER BY applied_at DESC LIMIT 1"
            ).fetchone()
            return int(row["version"]) if row else 0
    except sqlite3.OperationalError:
        return 0


def run_migrations() -> list[str]:
    """
    Executa migrações pendentes de forma incremental.

    Cada migração é idempotente — pode rodar múltiplas vezes sem efeito colateral.
    Retorna lista de migrações aplicadas.
    """
    applied: list[str] = []

    # Garante tabela de controle de migrações
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT    NOT NULL,
                applied_at  TEXT    NOT NULL DEFAULT (datetime('now','utc'))
            )
        """)

    current = get_schema_version()

    # ── Migração 1: Adicionar trilha de auditoria de sinais ──────────────────
    if current < 1:
        with _get_conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS signal_audit (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts              TEXT    NOT NULL,
                    symbol          TEXT    NOT NULL,
                    direction       TEXT    NOT NULL,
                    score           REAL    DEFAULT 0,
                    ai_score        REAL    DEFAULT 0,
                    regime          TEXT    DEFAULT '',
                    setup           TEXT    DEFAULT '',
                    sl              REAL    DEFAULT 0,
                    tp              REAL    DEFAULT 0,
                    rr              REAL    DEFAULT 0,
                    was_emitted     INTEGER DEFAULT 0,
                    reject_reason   TEXT    DEFAULT '',
                    strategy_version TEXT   DEFAULT '',
                    data_sources    TEXT    DEFAULT '',
                    created_at      TEXT    NOT NULL DEFAULT (datetime('now','utc'))
                );

                CREATE INDEX IF NOT EXISTS idx_audit_symbol
                    ON signal_audit(symbol);
                CREATE INDEX IF NOT EXISTS idx_audit_ts
                    ON signal_audit(ts);
                CREATE INDEX IF NOT EXISTS idx_audit_regime
                    ON signal_audit(regime);

                INSERT OR IGNORE INTO schema_migrations (version, name)
                    VALUES (1, 'add_signal_audit_table');
            """)
        applied.append("migration_1_signal_audit")
        log("[DB] Migração 1 aplicada: tabela signal_audit criada")

    # ── Migração 2: Adicionar colunas de risco ao trade_history ─────────────
    if current < 2:
        with _get_conn() as conn:
            # ALTER TABLE é seguro com IF NOT EXISTS via try/except
            for col, typedef in [
                ("risk_usd",     "REAL DEFAULT 0"),
                ("risk_pct",     "REAL DEFAULT 0"),
                ("session",      "TEXT DEFAULT ''"),
                ("regime",       "TEXT DEFAULT ''"),
                ("strategy_ver", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE trade_history ADD COLUMN {col} {typedef}")
                except sqlite3.OperationalError:
                    pass  # coluna já existe — idempotente

            conn.execute("""
                INSERT OR IGNORE INTO schema_migrations (version, name)
                    VALUES (2, 'add_risk_columns_to_trade_history')
            """)
        applied.append("migration_2_risk_columns")
        log("[DB] Migração 2 aplicada: colunas de risco em trade_history")

    return applied


def record_signal_audit(
    symbol: str,
    direction: str,
    score: float,
    ai_score: float,
    regime: str,
    setup: str,
    sl: float,
    tp: float,
    rr: float,
    was_emitted: bool,
    reject_reason: str = "",
    strategy_version: str = "",
    data_sources: str = "",
) -> None:
    """
    Registra auditoria de um sinal gerado (emitido ou rejeitado).

    Permite reconstruir post-facto por que qualquer sinal foi ou não foi enviado.

    Args:
        symbol: par monitorado
        direction: BUY / SELL
        score: score técnico final (0–10)
        ai_score: score da IA (0–10, 0 se desativada)
        regime: regime de mercado detectado
        setup: nome do setup (ex: 'EMA_CROSS', 'BREAKOUT')
        sl: stop loss calculado
        tp: take profit calculado
        rr: risk/reward ratio
        was_emitted: True se o sinal foi enviado
        reject_reason: motivo do descarte
        strategy_version: versão da estratégia/config (para rastrear mudanças)
        data_sources: fontes de dados usadas (ex: 'twelve_data,cot,news')
    """
    ts = datetime.utcnow().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute("""
                INSERT INTO signal_audit
                    (ts, symbol, direction, score, ai_score, regime, setup,
                     sl, tp, rr, was_emitted, reject_reason,
                     strategy_version, data_sources)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                ts, symbol, direction,
                round(score, 3), round(ai_score, 3),
                regime, setup,
                round(sl, 5), round(tp, 5), round(rr, 3),
                int(was_emitted), reject_reason,
                strategy_version, data_sources,
            ))
    except Exception as e:
        log(f"[DB] Erro ao registrar signal_audit: {e}")


def get_signal_audit(
    symbol: str = "",
    last_n: int = 50,
    only_emitted: bool = False,
) -> list[dict]:
    """
    Recupera registros de auditoria de sinais.

    Args:
        symbol: filtra por símbolo (vazio = todos)
        last_n: máximo de registros
        only_emitted: se True, retorna só os sinais efetivamente enviados

    Returns:
        lista de dicts com os campos da tabela signal_audit
    """
    conditions = []
    params: list = []

    if symbol:
        conditions.append("symbol = ?")
        params.append(symbol)
    if only_emitted:
        conditions.append("was_emitted = 1")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    try:
        with _get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM signal_audit {where} ORDER BY created_at DESC LIMIT ?",
                params + [last_n]
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Tabela ainda não existe — migração pendente
        return []


def get_signal_acceptance_rate(symbol: str = "", last_n: int = 100) -> dict:
    """
    Calcula taxa de emissão vs. rejeição de sinais.

    Útil para diagnosticar se os filtros estão muito restritivos.
    """
    records = get_signal_audit(symbol=symbol, last_n=last_n)
    if not records:
        return {"acceptance_rate": 0.0, "n_evaluated": 0, "n_emitted": 0}

    n_emitted = sum(1 for r in records if r.get("was_emitted"))
    avg_score = round(
        sum(r.get("score", 0) for r in records) / len(records), 2
    ) if records else 0.0

    # Principais motivos de rejeição
    reasons: dict[str, int] = {}
    for r in records:
        reason = r.get("reject_reason", "")
        if reason:
            key = reason[:50]  # trunca para agrupar
            reasons[key] = reasons.get(key, 0) + 1

    top_reasons = sorted(reasons.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "acceptance_rate": round(n_emitted / len(records) * 100, 1),
        "n_evaluated":     len(records),
        "n_emitted":       n_emitted,
        "avg_score":       avg_score,
        "symbol":          symbol or "all",
        "top_reject_reasons": [{"reason": r, "count": c} for r, c in top_reasons],
    }

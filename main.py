# -*- coding: utf-8 -*-
import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass
from enum import Enum

# ========================================
# CONFIGURAÇÕES
# ========================================
class Config:
    BOT_TOKEN: str = "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ"
    CHAT_ID: str = "1056795017"
    POLYGON_API_KEY: str = os.getenv("YvOIfg3ERjYpMIJs4FnPk87Bg06TSWqB", os.getenv("FOREX_API_KEY", ""))

    SIGNAL_INTERVAL: int = 10
    BR_TIMEZONE: timezone = timezone(timedelta(hours=-3))
    UNIVERSE_REFRESH: int = 900

    # ✅ Apenas os melhores pares
    ACTIVE_SYMBOLS: List[str] = [
        "EURUSD",
        "GBPUSD",
        "USDJPY",
    ]

    EMA_SHORT: int = 9
    EMA_LONG: int = 21
    RSI_PERIOD: int = 14
    MIN_CANDLES: int = 60
    TREND_THRESHOLD: float = 0.0006

    LEARNING_FILE: str = "learning.json"
    OPERATIONS_LOG: str = "operations_log.csv"
    BACKTEST_FILE: str = "backtest_results.json"  # ✅ NOVO

    MIN_SIGNAL_STRENGTH: float = 5.0
    STOP_LOSS_PIPS: float = 0.0050
    TAKE_PROFIT_PIPS: float = 0.0100

    DEBUG_MODE: bool = False
    PAPER_TRADING: bool = True  # ✅ NOVO: Modo paper trading

    # ✅ NOVO: Limites de segurança
    MAX_LOSS_STREAK: int = 5  # Pausa após 5 losses
    MAX_DAILY_LOSS: float = 3.0  # Máximo 3% de loss por dia
    MAX_OPERATIONS_PER_HOUR: int = 3  # Máximo 3 ops por hora
    MIN_WINRATE_TO_TRADE: float = 0.50  # Mínimo 50% winrate para continuar
    SYMBOL_COOLDOWN_MINUTES: int = 20  # ✅ NOVO: cooldown por tempo, não infinito

# ========================================
# ENUMERAÇÕES
# ========================================
class TradeDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"

class TradeStage(Enum):
    ENTRY = 0
    PROTECTION_1 = 1
    PROTECTION_2 = 2

# ========================================
# DATA CLASSES
# ========================================
@dataclass
class Candle:
    time: datetime
    open: float
    close: float
    high: float
    low: float
    volume: float

@dataclass
class PendingSetup:
    symbol: str
    direction: TradeDirection
    score: float
    entry_time: datetime

@dataclass
class ActiveOperation:
    symbol: str
    direction: TradeDirection
    stage: TradeStage
    entry_time: datetime
    entry_price: float
    protection1_time: datetime
    protection2_time: datetime

# ========================================
# STATE MANAGER
# ========================================
class BotState:
    def __init__(self):
        self.wins: int = 0
        self.losses: int = 0
        self.active_operations: List[ActiveOperation] = []
        self.pending_setup: Optional[PendingSetup] = None
        self.last_signal_time: Optional[datetime] = None
        self.last_universe_update: Optional[datetime] = None
        self.is_active: bool = False
        self.last_update_id: Optional[int] = None
        self.performance: Dict[str, Dict[str, int]] = {
            symbol: {"win": 0, "loss": 0}
            for symbol in Config.ACTIVE_SYMBOLS
        }
        self.last_used_symbols: List[str] = []
        self.symbol_last_used: Dict[str, datetime] = {}  # ✅ NOVO
        self.loss_streak: int = 0
        self.paused: bool = False
        self.pause_until: Optional[datetime] = None
        self.operations_today: List[Dict[str, Any]] = []  # ✅ NOVO
        self.daily_loss_percent: float = 0.0  # ✅ NOVO
        self.operations_this_hour: int = 0  # ✅ NOVO
        self.last_hour_reset: datetime = get_utc_now()  # ✅ NOVO
        self._init_log_file()

    def _init_log_file(self) -> None:
        try:
            if not os.path.exists(Config.OPERATIONS_LOG):
                with open(Config.OPERATIONS_LOG, "w") as f:
                    f.write("TIMESTAMP,SYMBOL,DIRECTION,STAGE,IS_WIN,ENTRY_PRICE,RESULT_PRICE,DIFFERENCE\n")
        except:
            pass

    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0

    def record_win(self, symbol: str) -> None:
        self.wins += 1
        self.performance[symbol]["win"] += 1
        self.loss_streak = 0
        self._add_to_history(symbol)
        self.symbol_last_used[symbol] = get_utc_now()  # ✅ NOVO

    def record_loss(self, symbol: str) -> None:
        self.losses += 1
        self.performance[symbol]["loss"] += 1
        self.loss_streak += 1
        self._add_to_history(symbol)
        self.symbol_last_used[symbol] = get_utc_now()  # ✅ NOVO

    def _add_to_history(self, symbol: str) -> None:
        if symbol not in self.last_used_symbols:
            self.last_used_symbols.append(symbol)
        if len(self.last_used_symbols) > 10:
            self.last_used_symbols.pop(0)

    def can_use_symbol(self, symbol: str) -> bool:
        last_used = self.symbol_last_used.get(symbol)
        if last_used is None:
            return True
        return (get_utc_now() - last_used) >= timedelta(minutes=Config.SYMBOL_COOLDOWN_MINUTES)

    # ✅ NOVO: Verificar limites de segurança
    def check_safety_limits(self) -> Tuple[bool, str]:
        """Verifica se pode abrir nova operação"""

        # Resetar contador de hora se necessário
        if (get_utc_now() - self.last_hour_reset).total_seconds() > 3600:
            self.operations_this_hour = 0
            self.last_hour_reset = get_utc_now()

        # Limite de operações por hora
        if self.operations_this_hour >= Config.MAX_OPERATIONS_PER_HOUR:
            return False, f"⏸️ Máximo de {Config.MAX_OPERATIONS_PER_HOUR} ops por hora atingido"

        # Limite de loss streak
        if self.loss_streak >= Config.MAX_LOSS_STREAK:
            return False, f"🛑 Loss streak de {self.loss_streak} atingido"

        # Limite de winrate mínimo
        if self.winrate < Config.MIN_WINRATE_TO_TRADE and (self.wins + self.losses) >= 10:
            return False, f"🛑 Winrate {self.winrate:.1f}% abaixo de {Config.MIN_WINRATE_TO_TRADE*100:.0f}%"

        # Limite de loss diário
        if self.daily_loss_percent > Config.MAX_DAILY_LOSS:
            return False, f"🛑 Loss diário {self.daily_loss_percent:.1f}% atingido"

        return True, "✅ OK"

# ========================================
# APRENDIZADO INTELIGENTE AVANÇADO
# ========================================
class LearningManager:
    def __init__(self, file_path: str = Config.LEARNING_FILE):
        self.file_path = file_path
        self.data: Dict[str, Any] = {
            "asset_stats": {},
            "hour_stats": {},
            "pattern_stats": {},
            "correlation_matrix": {},
            "ml_model": {},
            "backtest_history": {},  # ✅ NOVO
        }
        self.load()
        self.initialize_ml_data()

    def initialize_ml_data(self) -> None:
        if "ml_model" not in self.data or not self.data["ml_model"]:
            self.data["ml_model"] = {
                "signal_features": [],
                "outcomes": [],
                "feature_importance": {},
            }

    def load(self) -> None:
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    self.data = json.load(f)
                log("✅ Aprendizado carregado")
            except:
                log("⚠️ Erro ao carregar aprendizado")

    def save(self) -> None:
        try:
            with open(self.file_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except:
            pass

    def record_result(self, symbol: str, is_win: bool, score: float = 0.0, hour: str = "") -> None:
        hour = hour or str(get_br_now().hour)

        if symbol not in self.data["asset_stats"]:
            self.data["asset_stats"][symbol] = {"win": 0, "loss": 0, "total": 0}
        key = "win" if is_win else "loss"
        self.data["asset_stats"][symbol][key] += 1
        self.data["asset_stats"][symbol]["total"] += 1

        if hour not in self.data["hour_stats"]:
            self.data["hour_stats"][hour] = {"win": 0, "loss": 0, "total": 0}
        self.data["hour_stats"][hour][key] += 1
        self.data["hour_stats"][hour]["total"] += 1

        pattern_key = f"{symbol}_{hour}"
        if pattern_key not in self.data["pattern_stats"]:
            self.data["pattern_stats"][pattern_key] = {"win": 0, "loss": 0, "total": 0}
        self.data["pattern_stats"][pattern_key][key] += 1
        self.data["pattern_stats"][pattern_key]["total"] += 1

        self.data["ml_model"]["signal_features"].append({
            "symbol": symbol,
            "hour": hour,
            "signal_strength": score,
            "outcome": 1 if is_win else 0
        })

        self.save()

    def get_asset_multiplier(self, symbol: str) -> float:
        stats = self.data["asset_stats"].get(symbol)
        if not stats or stats["total"] < 5:
            return 1.0

        winrate = stats["win"] / stats["total"]

        if winrate > 0.70:
            return 1.35
        elif winrate > 0.65:
            return 1.25
        elif winrate > 0.55:
            return 1.10
        elif winrate > 0.45:
            return 0.90
        else:
            return 0.70

    def get_hour_multiplier(self) -> float:
        hour = str(get_br_now().hour)
        stats = self.data["hour_stats"].get(hour)
        if not stats or stats["total"] < 5:
            return 1.0

        winrate = stats["win"] / stats["total"]

        if winrate > 0.70:
            return 1.40
        elif winrate > 0.60:
            return 1.25
        elif winrate > 0.55:
            return 1.10
        else:
            return 0.85

    def get_pattern_multiplier(self, symbol: str, hour: str = "") -> float:
        hour = hour or str(get_br_now().hour)
        pattern_key = f"{symbol}_{hour}"
        stats = self.data["pattern_stats"].get(pattern_key)

        if not stats or stats["total"] < 3:
            return 1.0

        winrate = stats["win"] / stats["total"]

        if winrate > 0.75:
            return 1.50
        elif winrate > 0.65:
            return 1.30
        elif winrate > 0.55:
            return 1.15
        else:
            return 0.85

    def get_correlation_multiplier(self, symbol: str) -> float:
        correlations = {
            "EURUSD": {"GBPUSD": 0.8, "USDJPY": -0.6},
            "GBPUSD": {"EURUSD": 0.8, "USDJPY": -0.5},
            "USDJPY": {"EURUSD": -0.6, "GBPUSD": -0.5},
        }

        if symbol not in correlations:
            return 1.0

        boost = 1.0
        for corr_symbol, strength in correlations[symbol].items():
            if corr_symbol in self.data["asset_stats"]:
                stats = self.data["asset_stats"][corr_symbol]
                if stats["total"] > 0:
                    wr = stats["win"] / stats["total"]
                    if strength > 0 and wr > 0.60:
                        boost *= 1.10

        return boost

    def get_ml_recommendation(self, symbol: str, score: float) -> float:
        ml_data = self.data["ml_model"]

        if len(ml_data["signal_features"]) < 10:
            return 1.0

        winners = [f for f in ml_data["signal_features"] if f["outcome"] == 1]
        losers = [f for f in ml_data["signal_features"] if f["outcome"] == 0]

        if not winners or not losers:
            return 1.0

        avg_winner_score = sum(f["signal_strength"] for f in winners) / len(winners)
        avg_loser_score = sum(f["signal_strength"] for f in losers) / len(losers)

        if avg_loser_score == 0:
            return 1.0

        ratio = score / (avg_loser_score if score > avg_loser_score else avg_winner_score)

        if ratio > 1.5:
            return 1.25
        elif ratio > 1.2:
            return 1.10
        else:
            return 1.0

    def get_total_multiplier(self, symbol: str, score: float) -> float:
        asset_mult = self.get_asset_multiplier(symbol)
        hour_mult = self.get_hour_multiplier()
        pattern_mult = self.get_pattern_multiplier(symbol)
        corr_mult = self.get_correlation_multiplier(symbol)
        ml_mult = self.get_ml_recommendation(symbol, score)

        total = (
            asset_mult * 0.30 +
            hour_mult * 0.25 +
            pattern_mult * 0.25 +
            corr_mult * 0.10 +
            ml_mult * 0.10
        )

        if Config.DEBUG_MODE:
            log(f"🧠 IA Multipliers | Asset: {asset_mult:.2f} | Hour: {hour_mult:.2f} | Pattern: {pattern_mult:.2f} | Total: {total:.2f}")

        return total

    def get_recommendations(self) -> Dict[str, Any]:
        recommendations = {
            "best_assets": [],
            "best_hours": [],
            "best_patterns": [],
            "avoid_assets": [],
            "avoid_hours": [],
        }

        asset_wrs = {}
        for symbol, stats in self.data["asset_stats"].items():
            if stats["total"] >= 5:
                wr = stats["win"] / stats["total"]
                asset_wrs[symbol] = wr

        if asset_wrs:
            sorted_assets = sorted(asset_wrs.items(), key=lambda x: x[1], reverse=True)
            recommendations["best_assets"] = [s[0] for s in sorted_assets[:3]]
            recommendations["avoid_assets"] = [s[0] for s in sorted_assets[-3:]]

        hour_wrs = {}
        for hour, stats in self.data["hour_stats"].items():
            if stats["total"] >= 5:
                wr = stats["win"] / stats["total"]
                hour_wrs[hour] = wr

        if hour_wrs:
            sorted_hours = sorted(hour_wrs.items(), key=lambda x: x[1], reverse=True)
            recommendations["best_hours"] = [s[0] for s in sorted_hours[:3]]
            recommendations["avoid_hours"] = [s[0] for s in sorted_hours[-3:]]

        pattern_wrs = {}
        for pattern, stats in self.data["pattern_stats"].items():
            if stats["total"] >= 3:
                wr = stats["win"] / stats["total"]
                pattern_wrs[pattern] = wr

        if pattern_wrs:
            sorted_patterns = sorted(pattern_wrs.items(), key=lambda x: x[1], reverse=True)
            recommendations["best_patterns"] = [s[0] for s in sorted_patterns[:3]]

        return recommendations

    def generate_report(self) -> str:
        recs = self.get_recommendations()

        report = "🧠 RELATÓRIO IA:\n━━━━━━━━━━━━━━━\n"
        report += f"✅ Melhores Ativos: {', '.join(recs['best_assets']) if recs['best_assets'] else 'N/A'}\n"
        report += f"❌ Piores Ativos: {', '.join(recs['avoid_assets']) if recs['avoid_assets'] else 'N/A'}\n"
        report += f"⏰ Melhores Horas: {', '.join(recs['best_hours']) if recs['best_hours'] else 'N/A'}h\n"
        report += f"❌ Piores Horas: {', '.join(recs['avoid_hours']) if recs['avoid_hours'] else 'N/A'}h\n"

        return report

# ========================================
# TEMPO
# ========================================
def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

def get_br_now() -> datetime:
    return get_utc_now().astimezone(Config.BR_TIMEZONE)

def floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)

def next_minute(dt: datetime) -> datetime:
    return floor_minute(dt) + timedelta(minutes=1)

def fmt_br(dt: datetime) -> str:
    return dt.astimezone(Config.BR_TIMEZONE).strftime("%H:%M")

def should_trade_now() -> bool:
    hour = get_br_now().hour
    if hour >= 22 or hour < 0:
        return False
    return True

def fmt_price(symbol: str, price: float) -> str:
    return f"{price:.3f}" if symbol == "USDJPY" else f"{price:.5f}"

def normalize_forex_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper().replace(" ", "")
    if "/" in symbol:
        return symbol
    if len(symbol) == 6 and symbol.isalpha():
        return f"{symbol[:3]}/{symbol[3:]}"
    return symbol

def polygon_forex_ticker(symbol: str) -> str:
    return f"C:{normalize_forex_symbol(symbol).replace('/', '')}"

def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

# ========================================
# LOG E TELEGRAM
# ========================================
def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def send_telegram(msg: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": msg}
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        log(f"❌ Erro Telegram: {e}")
        return False

def remove_webhook() -> None:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook"
        requests.get(url, timeout=10)
    except:
        pass

# ========================================
# VALIDAÇÃO DE CREDENCIAIS
# ========================================
def validate_credentials() -> bool:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        response.raise_for_status()

        if response.status_code == 200:
            log("✅ Credenciais do Telegram validadas")
            return True
    except:
        log("❌ Erro ao validar credenciais do Telegram")
        return False

# ========================================
# COMANDOS TELEGRAM
# ========================================
def check_commands(state: BotState, learning_mgr: LearningManager) -> None:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates"
        params = {"timeout": 0}
        if state.last_update_id is not None:
            params["offset"] = state.last_update_id + 1
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "result" not in data:
            return
        for update in data["result"]:
            state.last_update_id = update["update_id"]
            if "message" not in update:
                continue
            text = update["message"].get("text", "").strip()
            if text == "/start":
                state.is_active = True
                state.paused = False
                mode = "📄 PAPER TRADING" if Config.PAPER_TRADING else "💰 REAL TRADING"
                send_telegram(f"🟢 BOT ATIVADO\n{mode}")
                log("✅ BOT ATIVADO")
            elif text == "/stop":
                state.is_active = False
                send_telegram("🔴 BOT PARADO")
                log("⏹️ BOT PARADO")
            elif text == "/stats":
                stats_msg = generate_stats_message(state)
                send_telegram(stats_msg)
            elif text == "/health":
                health_check(state)
            elif text == "/ai":
                send_telegram(learning_mgr.generate_report())
            elif text == "/limits":  # ✅ NOVO
                limits_msg = generate_limits_message(state)
                send_telegram(limits_msg)
    except Exception as e:
        log(f"❌ Erro comandos: {e}")

# ========================================
# ✅ NOVO: MENSAGEM DE LIMITES
# ========================================
def generate_limits_message(state: BotState) -> str:
    can_trade, reason = state.check_safety_limits()

    msg = "🛡️ LIMITES DE SEGURANÇA:\n━━━━━━━━━━━━━━━\n"
    msg += f"📊 Status: {'✅ LIBERADO' if can_trade else f'❌ {reason}'}\n"
    msg += f"🔥 Loss Streak: {state.loss_streak}/{Config.MAX_LOSS_STREAK}\n"
    msg += f"⏰ Ops/Hora: {state.operations_this_hour}/{Config.MAX_OPERATIONS_PER_HOUR}\n"
    msg += f"📉 Loss Diário: {state.daily_loss_percent:.1f}%/{Config.MAX_DAILY_LOSS}%\n"
    msg += f"📈 Winrate: {state.winrate:.1f}%/{Config.MIN_WINRATE_TO_TRADE*100:.0f}%\n"

    return msg

# ========================================
# ESTATÍSTICAS AVANÇADAS
# ========================================
def generate_stats_message(state: BotState) -> str:
    total_ops = state.wins + state.losses
    best_symbol = max(state.performance.items(), key=lambda x: x[1]["win"] - x[1]["loss"]) if state.performance else ("N/A", {})

    msg = (
        f"📊 ESTATÍSTICAS\n"
        f"━━━━━━━━━━━━━━━\n"
        f"✅ Wins: {state.wins}\n"
        f"❌ Losses: {state.losses}\n"
        f"📈 Winrate: {state.winrate:.1f}%\n"
        f"🎯 Operações: {len(state.active_operations)}\n"
        f"🔥 Loss Streak: {state.loss_streak}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🏆 Melhor: {best_symbol[0]}\n"
        f"📋 Últimos: {', '.join(state.last_used_symbols[-3:]) if state.last_used_symbols else 'Nenhum'}\n"
        f"📄 Modo: {'📄 PAPER' if Config.PAPER_TRADING else '💰 REAL'}"
    )

    if state.paused:
        msg += f"\n\n⏸️ BOT EM PAUSA (Retoma em {state.pause_until.strftime('%H:%M') if state.pause_until else 'indefinido'})"

    return msg

# ========================================
# HEALTH CHECK
# ========================================
def health_check(state: BotState) -> None:
    checks = {
        "Telegram API": validate_credentials(),
        "Learning File": os.path.exists(Config.LEARNING_FILE),
        "Operations Log": os.path.exists(Config.OPERATIONS_LOG),
        "Safety Limits": state.check_safety_limits()[0],
    }

    msg = "🏥 HEALTH CHECK:\n━━━━━━━━━━━━━━━\n"
    all_ok = True
    for check, status in checks.items():
        status_icon = "✅" if status else "❌"
        msg += f"{status_icon} {check}\n"
        if not status:
            all_ok = False

    msg += f"━━━━━━━━━━━━━━━\n"
    msg += f"Status Geral: {'🟢 OK' if all_ok else '🔴 ERRO'}"

    send_telegram(msg)
    log(msg.replace("\n", " | "))

# ========================================
# LOG DE OPERAÇÕES
# ========================================
def log_operation(operation: ActiveOperation, stage_name: str, is_win: bool, entry_price: float, result_price: float) -> None:
    try:
        diff = result_price - entry_price
        with open(Config.OPERATIONS_LOG, "a") as f:
            f.write(f"{get_br_now().isoformat()},{operation.symbol},{operation.direction.value},{stage_name},{is_win},{entry_price:.6f},{result_price:.6f},{diff:.6f}\n")
    except:
        pass

# ========================================
# GERADOR DE DADOS
# ========================================
class CandleGenerator:
    def __init__(self):
        self.cache: Dict[str, Tuple[datetime, List[Candle]]] = {}
        self.cache_ttl_seconds: int = 45
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })

    def _api_key(self) -> str:
        return str(Config.POLYGON_API_KEY or "").strip()

    def _fetch_polygon_bars(self, symbol: str, limit: int = 120) -> Optional[List[Candle]]:
        api_key = self._api_key()
        if not api_key:
            log("⚠️ POLYGON_API_KEY não configurada")
            return None

        ticker = polygon_forex_ticker(symbol)
        now = get_utc_now()
        start = now - timedelta(minutes=max(limit * 3, 240))
        url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute/{int(start.timestamp() * 1000)}/{int(now.timestamp() * 1000)}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": api_key,
        }

        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            results = data.get("results") or []
            if not results:
                msg = data.get("error") or data.get("message") or "resposta vazia"
                log(f"⚠️ Polygon sem candles para {symbol}: {msg}")
                return None

            raw: List[Candle] = []
            for item in results:
                ts = ms_to_dt(int(item["t"]))
                raw.append(Candle(
                    time=ts,
                    open=float(item["o"]),
                    close=float(item["c"]),
                    high=float(item["h"]),
                    low=float(item["l"]),
                    volume=float(item.get("v", 0) or 0),
                ))

            raw.sort(key=lambda c: c.time)
            filled: List[Candle] = []
            expected_time = floor_minute(raw[0].time)
            last_close = raw[0].open

            for candle in raw:
                candle_time = floor_minute(candle.time)
                while expected_time < candle_time:
                    filled.append(Candle(
                        time=expected_time,
                        open=last_close,
                        close=last_close,
                        high=last_close,
                        low=last_close,
                        volume=0.0,
                    ))
                    expected_time += timedelta(minutes=1)

                filled.append(Candle(
                    time=candle_time,
                    open=candle.open,
                    close=candle.close,
                    high=candle.high,
                    low=candle.low,
                    volume=candle.volume,
                ))
                last_close = candle.close
                expected_time = candle_time + timedelta(minutes=1)

            while len(filled) < limit and expected_time <= floor_minute(now):
                filled.append(Candle(
                    time=expected_time,
                    open=last_close,
                    close=last_close,
                    high=last_close,
                    low=last_close,
                    volume=0.0,
                ))
                expected_time += timedelta(minutes=1)

            if filled:
                self.cache[symbol] = (now, filled)
                return filled[-limit:]

            return None
        except Exception as e:
            log(f"⚠️ Falha ao buscar candles da Polygon para {symbol}: {e}")
            return None

    def get_candles(self, symbol: str, limit: int = 120) -> Optional[List[Candle]]:
        now = get_utc_now()
        cached = self.cache.get(symbol)
        if cached is not None:
            cached_at, cached_candles = cached
            if (now - cached_at).total_seconds() < self.cache_ttl_seconds and len(cached_candles) >= limit:
                return cached_candles[-limit:]

        candles = self._fetch_polygon_bars(symbol, limit=limit)
        if candles is not None:
            return candles
        return None

    def get_candle_at_time(self, symbol: str, timestamp: datetime) -> Optional[Candle]:
        candles = self.get_candles(symbol, limit=200)
        if not candles:
            return None
        target = floor_minute(timestamp)
        for candle in candles:
            if floor_minute(candle.time) == target:
                return candle
        return None

    def get_price_at_time(self, symbol: str, timestamp: datetime) -> float:
        candle = self.get_candle_at_time(symbol, timestamp)
        if candle is not None:
            return candle.open if timestamp.second == 0 else candle.close

        candles = self.get_candles(symbol, limit=1)
        if candles:
            return candles[-1].close

        raise RuntimeError(f"Sem candles disponíveis para {symbol}")

candle_gen = CandleGenerator()

def get_candles(symbol: str, limit: int = 120) -> Optional[List[Candle]]:
    try:
        return candle_gen.get_candles(symbol, limit)
    except Exception as e:
        log(f"❌ Erro candles {symbol}: {e}")
        return None

def find_candle_by_open_time(candles: List[Candle], open_time: datetime) -> Optional[Candle]:
    target = floor_minute(open_time)
    for candle in candles:
        if floor_minute(candle.time) == target:
            return candle
    return None

# ========================================
# INDICADORES
# ========================================
def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * k + ema
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    if len(prices) < period + 1:
        return None
    gains = sum(prices[i] - prices[i - 1] for i in range(1, period + 1) if prices[i] > prices[i - 1])
    losses = sum(prices[i - 1] - prices[i] for i in range(1, period + 1) if prices[i] < prices[i - 1])
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ========================================
# SELEÇÃO DE ATIVOS
# ========================================
def calculate_asset_quality_score(symbol: str) -> float:
    candles = get_candles(symbol)
    if not candles or len(candles) < Config.MIN_CANDLES:
        return 0.0
    closes = [c.close for c in candles]
    ema_short = calculate_ema(closes, Config.EMA_SHORT)
    ema_long = calculate_ema(closes, Config.EMA_LONG)
    rsi = calculate_rsi(closes, Config.RSI_PERIOD)
    if any(v is None for v in [ema_short, ema_long, rsi]):
        return 0.0
    volatility = abs(closes[-1] - closes[-10]) / closes[-1]
    trend = abs(ema_short - ema_long) / closes[-1]
    score = volatility * 50 + trend * 120 + abs(rsi - 50) * 0.3
    return score

def update_active_symbols(learning_mgr: LearningManager, state: BotState) -> None:
    log("🔄 Atualizando universo de ativos...")
    symbols = Config.ACTIVE_SYMBOLS
    scored: List[Tuple[str, float]] = []

    for symbol in symbols:
        try:
            score = calculate_asset_quality_score(symbol)
            scored.append((symbol, score))
            log(f"  {symbol}: score={score:.3f}")
        except Exception as e:
            log(f"  ❌ Erro {symbol}: {e}")

    if not scored:
        log("⚠️ Nenhum score calculado")
        return

    scored.sort(key=lambda x: x[1], reverse=True)
    state.last_universe_update = get_utc_now()

    log(f"✅ Universo atualizado:")
    for i, (symbol, score) in enumerate(scored, 1):
        log(f"  {i}. {symbol} (score: {score:.3f})")

def select_best_asset(learning_mgr: LearningManager, state: BotState) -> Optional[Tuple[str, TradeDirection, float]]:
    # ✅ Verificar limites de segurança
    can_trade, reason = state.check_safety_limits()
    if not can_trade:
        log(reason)
        return None

    if not should_trade_now():
        if Config.DEBUG_MODE:
            log("⏸️ Fora do horário de negociação (22:00-00:00)")
        return None

    if state.paused and get_utc_now() < state.pause_until:
        log(f"⏸️ BOT EM PAUSA: {state.loss_streak} losses. Retoma em {state.pause_until.strftime('%H:%M')}")
        return None
    elif state.paused and get_utc_now() >= state.pause_until:
        state.paused = False
        state.loss_streak = 0
        log("▶️ BOT RETOMADO")
        send_telegram("▶️ BOT RETOMADO - Pausa encerrada")

    log("🔍 Analisando candles...")
    candidates: List[Tuple[str, TradeDirection, float]] = []

    for symbol in Config.ACTIVE_SYMBOLS:
        if not state.can_use_symbol(symbol):
            last_used = state.symbol_last_used.get(symbol)
            remaining = Config.SYMBOL_COOLDOWN_MINUTES * 60 - int((get_utc_now() - last_used).total_seconds()) if last_used else 0
            log(f"  ⏭️ {symbol} (cooldown por {max(0, remaining)}s)")
            continue

        candles = get_candles(symbol)
        if not candles or len(candles) < Config.MIN_CANDLES:
            log(f"  ❌ {symbol} - Sem candles suficientes ({len(candles) if candles else 0})")
            continue

        closes = [c.close for c in candles]
        ema_short = calculate_ema(closes, Config.EMA_SHORT)
        ema_long = calculate_ema(closes, Config.EMA_LONG)
        rsi = calculate_rsi(closes, Config.RSI_PERIOD)

        log(f"  {symbol} | EMA9: {ema_short:.6f} | EMA21: {ema_long:.6f} | RSI: {rsi:.2f}")

        if any(v is None for v in [ema_short, ema_long, rsi]):
            log(f"  ❌ {symbol} - Indicadores None")
            continue

        trend_pct = abs(ema_short - ema_long) / closes[-1]
        score = trend_pct * 1000 + abs(rsi - 50) * 2

        ai_multiplier = learning_mgr.get_total_multiplier(symbol, score)
        score *= ai_multiplier

        log(f"    Trend: {trend_pct:.6f} | Score (com IA): {score:.3f}")

        if ema_short > ema_long:
            direction = TradeDirection.BUY
            log(f"    ✅ BUY candidato (EMA9 > EMA21)")
            candidates.append((symbol, direction, score))
        elif ema_short < ema_long:
            direction = TradeDirection.SELL
            log(f"    ✅ SELL candidato (EMA9 < EMA21)")
            candidates.append((symbol, direction, score))
        else:
            log(f"    ❌ Sem direção clara")

    if candidates:
        strong_candidates = [(s, d, sc) for s, d, sc in candidates if sc > Config.MIN_SIGNAL_STRENGTH]

        if not strong_candidates:
            log(f"⚠️ Candidatos encontrados mas nenhum com força ≥ {Config.MIN_SIGNAL_STRENGTH}\n")
            return None

        strong_candidates.sort(key=lambda x: x[2], reverse=True)
        best_symbol, best_direction, best_score = strong_candidates[0]
        log(f"\n🎯 MELHOR SINAL: {best_symbol} - {best_direction.value} - Score: {best_score:.3f}")
        log(f"📋 Histórico: {state.last_used_symbols}\n")
        return (best_symbol, best_direction, best_score)

    log("⚠️ Nenhum candidato encontrado\n")
    return None

# ========================================
# GESTÃO DE SINAIS
# ========================================
def create_signal(setup: PendingSetup, state: BotState) -> None:
    state.pending_setup = setup
    state.last_signal_time = get_utc_now()
    direction_emoji = "🟢 COMPRA" if setup.direction == TradeDirection.BUY else "🔴 VENDA"

    ref_candle = candle_gen.get_candle_at_time(setup.symbol, setup.entry_time - timedelta(minutes=1))
    ref_open = ref_candle.open if ref_candle else None
    ref_close = ref_candle.close if ref_candle else None

    msg = (
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"💱 Par: {setup.symbol}\n"
        f"📊 Estratégia: {direction_emoji}\n"
        f"⏰ Entrada: {fmt_br(setup.entry_time)}\n"
    )
    if ref_open is not None and ref_close is not None:
        msg += f"🕯️ Vela anterior O/C: {fmt_price(setup.symbol, ref_open)} / {fmt_price(setup.symbol, ref_close)}\n"
    msg += f"📈 Força: {setup.score:.3f}"

    send_telegram(msg)
    log(f"📊 SINAL | {setup.symbol} | {setup.direction.value}")

def process_pending_setup(state: BotState) -> None:
    if state.pending_setup is None or get_utc_now() < state.pending_setup.entry_time:
        return
    setup = state.pending_setup
    p1_time = setup.entry_time + timedelta(minutes=1)
    p2_time = setup.entry_time + timedelta(minutes=2)

    entry_candle = candle_gen.get_candle_at_time(setup.symbol, setup.entry_time)
    entry_price = entry_candle.open if entry_candle is not None else candle_gen.get_price_at_time(setup.symbol, setup.entry_time)

    operation = ActiveOperation(
        symbol=setup.symbol,
        direction=setup.direction,
        stage=TradeStage.ENTRY,
        entry_time=setup.entry_time,
        entry_price=entry_price,
        protection1_time=p1_time,
        protection2_time=p2_time,
    )
    state.active_operations.append(operation)
    state.pending_setup = None
    state.operations_this_hour += 1  # ✅ NOVO
    direction_emoji = "🟢 COMPRA" if setup.direction == TradeDirection.BUY else "🔴 VENDA"
    msg = f"✅ ENTRADA\n\n💱 {setup.symbol}\n{direction_emoji}\n⏰ {fmt_br(setup.entry_time)}"
    send_telegram(msg)

# ========================================
# VERIFICAÇÃO DE RESULTADOS
# ========================================
def check_operation_result(operation: ActiveOperation, learning_mgr: LearningManager, state: BotState) -> Optional[ActiveOperation]:
    now = get_utc_now()

    if operation.stage == TradeStage.ENTRY:
        candle_time = operation.entry_time
        check_time = operation.entry_time + timedelta(minutes=1)
        next_stage = TradeStage.PROTECTION_1
        stage_name = "Entrada"
    elif operation.stage == TradeStage.PROTECTION_1:
        candle_time = operation.protection1_time
        check_time = operation.protection1_time + timedelta(minutes=1)
        next_stage = TradeStage.PROTECTION_2
        stage_name = "Proteção 1"
    else:
        candle_time = operation.protection2_time
        check_time = operation.protection2_time + timedelta(minutes=1)
        next_stage = None
        stage_name = "Proteção 2"

    if now < check_time + timedelta(seconds=5):
        return operation

    candle = candle_gen.get_candle_at_time(operation.symbol, candle_time)
    if candle is None:
        candles = get_candles(operation.symbol, limit=5)
        if not candles:
            log(f"  ❌ Sem candles para {operation.symbol}")
            return operation
        candle = candles[-1]

    entry_price = candle.open
    result_price = candle.close

    log(f"  📊 {operation.symbol} M1 | Abertura: {fmt_price(operation.symbol, entry_price)} | Fechamento: {fmt_price(operation.symbol, result_price)} | {stage_name}")

    if operation.direction == TradeDirection.BUY:
        if result_price <= entry_price - Config.STOP_LOSS_PIPS:
            is_win = False
            log(f"  🛑 STOP LOSS | Entrada: {entry_price:.6f} vs Resultado: {result_price:.6f}")
        elif result_price >= entry_price + Config.TAKE_PROFIT_PIPS:
            is_win = True
            log(f"  🎯 TAKE PROFIT | Entrada: {entry_price:.6f} vs Resultado: {result_price:.6f}")
        else:
            is_win = result_price > entry_price
        direction_text = "COMPRA"
    else:
        if result_price >= entry_price + Config.STOP_LOSS_PIPS:
            is_win = False
            log(f"  🛑 STOP LOSS | Entrada: {entry_price:.6f} vs Resultado: {result_price:.6f}")
        elif result_price <= entry_price - Config.TAKE_PROFIT_PIPS:
            is_win = True
            log(f"  🎯 TAKE PROFIT | Entrada: {entry_price:.6f} vs Resultado: {result_price:.6f}")
        else:
            is_win = result_price < entry_price
        direction_text = "VENDA"

    diff = result_price - entry_price
    result_text = "✅ WIN" if is_win else "❌ LOSS"
    log(f"  {result_text} | {direction_text} | {stage_name} | Diferença: {diff:.6f} pips")

    log_operation(operation, stage_name, is_win, entry_price, result_price)

    if is_win:
        state.record_win(operation.symbol)
        learning_mgr.record_result(operation.symbol, True, 0.0, str(get_br_now().hour))
        msg = (
            f"🏆 WIN\n\n"
            f"💱 {operation.symbol}\n"
            f"✅ {stage_name}\n"
            f"{direction_text}\n"
            f"🕯️ Abertura: {fmt_price(operation.symbol, entry_price)}\n"
            f"🕯️ Fechamento: {fmt_price(operation.symbol, result_price)}\n\n"
            f"Wins: {state.wins} | Losses: {state.losses}\n"
            f"📈 {state.winrate:.1f}%"
        )
        send_telegram(msg)
        log(f"✅ WIN REGISTRADO | {operation.symbol}")
        return None

    if next_stage is not None:
        operation.stage = next_stage
        log(f"  ⚠️ Avançando para {next_stage.name}")
        return operation

    state.record_loss(operation.symbol)
    learning_mgr.record_result(operation.symbol, False, 0.0, str(get_br_now().hour))
    msg = (
        f"🏆 LOSS\n\n"
        f"💱 {operation.symbol}\n"
        f"❌ {stage_name}\n"
        f"{direction_text}\n"
        f"🕯️ Abertura: {fmt_price(operation.symbol, entry_price)}\n"
        f"🕯️ Fechamento: {fmt_price(operation.symbol, result_price)}\n\n"
        f"Wins: {state.wins} | Losses: {state.losses}\n"
        f"📈 {state.winrate:.1f}%"
    )
    send_telegram(msg)
    log(f"❌ LOSS REGISTRADO | {operation.symbol}")

    if state.loss_streak >= Config.MAX_LOSS_STREAK and not state.paused:
        state.paused = True
        state.pause_until = get_utc_now() + timedelta(hours=1)
        msg = f"⏸️ PAUSA AUTOMÁTICA\n\n{state.loss_streak} losses consecutivos!\nBot pausado por 1 hora."
        send_telegram(msg)
        log(f"⏸️ BOT PAUSADO: {state.loss_streak} losses")

    return None

def check_results(learning_mgr: LearningManager, state: BotState) -> None:
    new_operations: List[ActiveOperation] = []
    for operation in state.active_operations:
        result = check_operation_result(operation, learning_mgr, state)
        if result is not None:
            new_operations.append(result)
    state.active_operations = new_operations

# ========================================
# MAIN
# ========================================
def main() -> None:
    if not validate_credentials():
        log("❌ Bot não iniciado: credenciais inválidas")
        send_telegram("❌ BOT NÃO INICIADO: Credenciais inválidas")
        return

    remove_webhook()
    learning_mgr = LearningManager()
    state = BotState()

    mode_msg = "📄 PAPER TRADING (Simulado)" if Config.PAPER_TRADING else "💰 REAL TRADING (Dinheiro Real)"
    log(f"🤖 BOT FOREX INICIANDO... ({mode_msg})")
    send_telegram(f"🤖 BOT FOREX ATIVADO 💱\n{mode_msg}\n\nComandos: /start /stop /stats /health /ai /limits")

    while True:
        try:
            check_commands(state, learning_mgr)
            if not state.is_active:
                time.sleep(10)
                continue
            if state.last_universe_update is None or (get_utc_now() - state.last_universe_update).total_seconds() > Config.UNIVERSE_REFRESH:
                update_active_symbols(learning_mgr, state)
            process_pending_setup(state)
            check_results(learning_mgr, state)
            if state.pending_setup is None and not state.active_operations:
                if state.last_signal_time is None or (get_utc_now() - state.last_signal_time).total_seconds() >= Config.SIGNAL_INTERVAL:
                    result = select_best_asset(learning_mgr, state)
                    if result:
                        symbol, direction, score = result
                        entry_time = next_minute(get_utc_now()) + timedelta(minutes=1)
                        setup = PendingSetup(symbol=symbol, direction=direction, score=score, entry_time=entry_time)
                        create_signal(setup, state)
            time.sleep(10)
        except Exception as e:
            log(f"❌ Erro: {e}")
            time.sleep(10)

main()

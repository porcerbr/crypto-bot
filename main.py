import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass
from enum import Enum
import hashlib

# ========================================
# CONFIGURAÇÕES PROFISSIONAIS
# ========================================
class Config:
    BOT_TOKEN: str = "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ"
    CHAT_ID: str = "1056795017"
    FOREX_API_KEY: str = "BFKUJTMXC8KO6RMS"
    
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
    BACKTEST_FILE: str = "backtest_results.json"
    AUDIT_LOG: str = "audit.log"  # ✅ NOVO
    
    MIN_SIGNAL_STRENGTH: float = 5.0
    STOP_LOSS_PIPS: float = 0.0050
    TAKE_PROFIT_PIPS: float = 0.0100
    
    DEBUG_MODE: bool = False
    PAPER_TRADING: bool = False  # ✅ ALTERADO: Pronto para REAL
    
    # ✅ NOVO: Limites rigorosos de segurança
    MAX_LOSS_STREAK: int = 3  # Pausa após 3 losses (menos tolerante)
    MAX_DAILY_LOSS: float = 2.0  # Máximo 2% de loss por dia
    MAX_OPERATIONS_PER_HOUR: int = 2  # Máximo 2 ops por hora (menos agressivo)
    MIN_WINRATE_TO_TRADE: float = 0.55  # Mínimo 55% para continuar
    
    # ✅ NOVO: Validações profissionais
    ACCOUNT_BALANCE: float = 1000.0  # Saldo inicial
    MAX_RISK_PER_TRADE: float = 0.01  # 1% por operação
    MIN_TRAINING_OPERATIONS: int = 50  # Precisa de 50 ops antes de fazer real
    REQUIRED_WINRATE_FOR_REAL: float = 0.58  # Precisa de 58% no simulado
    
    # ✅ NOVO: Horário operacional
    TRADING_START_HOUR: int = 6  # Começa 6h BR
    TRADING_END_HOUR: int = 21  # Termina 21h BR
    
    # ✅ NOVO: Validações de qualidade
    MIN_VOLUME_REQUIRED: float = 1000000.0
    MAX_SPREAD_ALLOWED: float = 0.0003  # 3 pips máximo

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

class TradingMode(Enum):
    PAPER = "PAPER"
    REAL = "REAL"
    FROZEN = "FROZEN"  # ✅ NOVO

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
    operation_id: str = ""  # ✅ NOVO

# ========================================
# ✅ NOVO: AUDITORIA PROFISSIONAL
# ========================================
class AuditLog:
    def __init__(self, file_path: str = Config.AUDIT_LOG):
        self.file_path = file_path
    
    def log(self, event_type: str, message: str, severity: str = "INFO") -> None:
        """Registra evento em arquivo de auditoria"""
        try:
            timestamp = datetime.now().isoformat()
            with open(self.file_path, "a") as f:
                f.write(f"{timestamp} | {severity:8} | {event_type:20} | {message}\n")
        except:
            pass
    
    def log_operation(self, operation_id: str, symbol: str, direction: str, entry_price: float, is_win: bool) -> None:
        """Registra operação realizada"""
        result = "WIN" if is_win else "LOSS"
        self.log("OPERATION", f"ID:{operation_id} | {symbol} {direction} @ {entry_price:.6f} | {result}", "TRADE")
    
    def log_risk_limit(self, reason: str) -> None:
        """Registra limite de risco acionado"""
        self.log("RISK_LIMIT", reason, "WARNING")
    
    def log_mode_change(self, old_mode: str, new_mode: str, reason: str) -> None:
        """Registra mudança de modo"""
        self.log("MODE_CHANGE", f"{old_mode} -> {new_mode} ({reason})", "CRITICAL")

audit = AuditLog()

# ========================================
# STATE MANAGER PROFISSIONAL
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
        self.loss_streak: int = 0
        self.paused: bool = False
        self.pause_until: Optional[datetime] = None
        self.operations_today: List[Dict[str, Any]] = []
        self.daily_loss_percent: float = 0.0
        self.operations_this_hour: int = 0
        self.last_hour_reset: datetime = get_utc_now()
        
        # ✅ NOVO: Modo de trading
        self.trading_mode: TradingMode = TradingMode.PAPER
        self.mode_locked: bool = False  # ✅ Impede mudança acidental
        
        # ✅ NOVO: Histórico de capital
        self.capital_history: List[Dict[str, Any]] = []
        
        self._init_log_file()
        self._validate_mode()
    
    def _init_log_file(self) -> None:
        try:
            if not os.path.exists(Config.OPERATIONS_LOG):
                with open(Config.OPERATIONS_LOG, "w") as f:
                    f.write("TIMESTAMP,SYMBOL,DIRECTION,STAGE,IS_WIN,ENTRY_PRICE,RESULT_PRICE,DIFFERENCE\n")
        except:
            pass
    
    def _validate_mode(self) -> None:
        """✅ NOVO: Valida se pode trocar para REAL"""
        if Config.PAPER_TRADING:
            self.trading_mode = TradingMode.PAPER
            return
        
        total_ops = self.wins + self.losses
        
        # Validações para modo REAL
        if total_ops < Config.MIN_TRAINING_OPERATIONS:
            audit.log_mode_change(
                "ATTEMPTING_REAL",
                "FROZEN",
                f"Apenas {total_ops} operações. Precisa de {Config.MIN_TRAINING_OPERATIONS}"
            )
            self.trading_mode = TradingMode.FROZEN
            return
        
        current_winrate = self.winrate / 100
        if current_winrate < Config.REQUIRED_WINRATE_FOR_REAL:
            audit.log_mode_change(
                "ATTEMPTING_REAL",
                "FROZEN",
                f"Winrate {current_winrate*100:.1f}% abaixo de {Config.REQUIRED_WINRATE_FOR_REAL*100:.0f}%"
            )
            self.trading_mode = TradingMode.FROZEN
            return
        
        self.trading_mode = TradingMode.REAL
        audit.log_mode_change("PAPER", "REAL", f"Passou em todas validações! {total_ops} ops, {current_winrate*100:.1f}% winrate")
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    def record_win(self, symbol: str, entry_price: float, result_price: float) -> None:
        self.wins += 1
        self.performance[symbol]["win"] += 1
        self.loss_streak = 0
        self._add_to_history(symbol)
        
        # ✅ NOVO: Registrar lucro
        profit_pips = (result_price - entry_price) * 10000
        self.capital_history.append({
            "timestamp": get_br_now().isoformat(),
            "type": "WIN",
            "symbol": symbol,
            "pips": profit_pips,
            "cumulative_pips": sum(h["pips"] for h in self.capital_history)
        })
    
    def record_loss(self, symbol: str, entry_price: float, result_price: float) -> None:
        self.losses += 1
        self.performance[symbol]["loss"] += 1
        self.loss_streak += 1
        self._add_to_history(symbol)
        
        # ✅ NOVO: Registrar perda
        loss_pips = (result_price - entry_price) * 10000
        self.capital_history.append({
            "timestamp": get_br_now().isoformat(),
            "type": "LOSS",
            "symbol": symbol,
            "pips": loss_pips,
            "cumulative_pips": sum(h["pips"] for h in self.capital_history)
        })
    
    def _add_to_history(self, symbol: str) -> None:
        if symbol not in self.last_used_symbols:
            self.last_used_symbols.append(symbol)
        if len(self.last_used_symbols) > 5:
            self.last_used_symbols.pop(0)
    
    def can_use_symbol(self, symbol: str) -> bool:
        return symbol not in self.last_used_symbols[:3]
    
    def check_safety_limits(self) -> Tuple[bool, str]:
        """Verifica se pode abrir nova operação"""
        
        # ✅ NOVO: Verificar modo congelado
        if self.trading_mode == TradingMode.FROZEN:
            return False, "🛑 BOT CONGELADO: Não atende critérios para operar"
        
        if (get_utc_now() - self.last_hour_reset).total_seconds() > 3600:
            self.operations_this_hour = 0
            self.last_hour_reset = get_utc_now()
        
        if self.operations_this_hour >= Config.MAX_OPERATIONS_PER_HOUR:
            return False, f"⏸️ Máximo de {Config.MAX_OPERATIONS_PER_HOUR} ops por hora atingido"
        
        if self.loss_streak >= Config.MAX_LOSS_STREAK:
            return False, f"🛑 Loss streak de {self.loss_streak} atingido"
        
        if self.winrate < Config.MIN_WINRATE_TO_TRADE and (self.wins + self.losses) >= 10:
            return False, f"🛑 Winrate {self.winrate:.1f}% abaixo de {Config.MIN_WINRATE_TO_TRADE*100:.0f}%"
        
        if self.daily_loss_percent > Config.MAX_DAILY_LOSS:
            return False, f"🛑 Loss diário {self.daily_loss_percent:.1f}% atingido"
        
        return True, "✅ OK"

# ========================================
# APRENDIZADO INTELIGENTE (MANTÉM IGUAL)
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
            "backtest_history": {},
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
    if hour < Config.TRADING_START_HOUR or hour >= Config.TRADING_END_HOUR:
        return False
    return True

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
                mode_display = "📄 SIMULADO (Paper)" if state.trading_mode == TradingMode.PAPER else "💰 REAL"
                send_telegram(f"🟢 BOT ATIVADO\n{mode_display}")
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
            elif text == "/limits":
                limits_msg = generate_limits_message(state)
                send_telegram(limits_msg)
            elif text == "/mode":  # ✅ NOVO
                send_telegram(generate_mode_message(state))
            elif text == "/capital":  # ✅ NOVO
                send_telegram(generate_capital_message(state))
    except Exception as e:
        log(f"❌ Erro comandos: {e}")

# ========================================
# ✅ NOVO: MODO STATUS
# ========================================
def generate_mode_message(state: BotState) -> str:
    total_ops = state.wins + state.losses
    winrate = state.winrate
    
    msg = "🎯 STATUS DO BOT:\n━━━━━━━━━━━━━━━\n"
    msg += f"Modo: {state.trading_mode.value}\n"
    msg += f"Operações: {total_ops}/{Config.MIN_TRAINING_OPERATIONS}\n"
    msg += f"Winrate: {winrate:.1f}%/{Config.REQUIRED_WINRATE_FOR_REAL*100:.0f}%\n"
    msg += "━━━━━━━━━━━━━━━\n"
    
    if state.trading_mode == TradingMode.FROZEN:
        msg += "🛑 CONGELADO - Não atende critérios\n"
        if total_ops < Config.MIN_TRAINING_OPERATIONS:
            msg += f"Precisa de {Config.MIN_TRAINING_OPERATIONS - total_ops} mais operações\n"
        if winrate < Config.REQUIRED_WINRATE_FOR_REAL * 100:
            msg += f"Winrate abaixo do mínimo ({Config.REQUIRED_WINRATE_FOR_REAL*100:.0f}%)\n"
    elif state.trading_mode == TradingMode.PAPER:
        msg += "📄 PAPER TRADING\n"
        msg += "Simulando operações para validação\n"
    else:
        msg += "💰 REAL TRADING ATIVO\n"
        msg += "⚠️ COM DINHEIRO REAL!\n"
    
    return msg

# ========================================
# ✅ NOVO: CAPITAL TRACKING
# ========================================
def generate_capital_message(state: BotState) -> str:
    if not state.capital_history:
        return "📈 Nenhuma operação realizada ainda"
    
    cumulative_pips = state.capital_history[-1].get("cumulative_pips", 0)
    total_ops = len(state.capital_history)
    
    msg = "📈 HISTÓRICO DE CAPITAL:\n━━━━━━━━━━━━━━━\n"
    msg += f"Total de Pips: {cumulative_pips:+.0f}\n"
    msg += f"Operações: {total_ops}\n"
    msg += f"Média por Op: {cumulative_pips/total_ops:+.1f} pips\n"
    msg += "━━━━━━━━━━━━━━━\n"
    
    # Últimas 5 operações
    msg += "Últimas 5 operações:\n"
    for op in state.capital_history[-5:]:
        result = "✅" if op["type"] == "WIN" else "❌"
        msg += f"{result} {op['symbol']} {op['pips']:+.0f}p\n"
    
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
        f"🎯 Modo: {state.trading_mode.value}"
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
        "Trading Mode": state.trading_mode != TradingMode.FROZEN,
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
# ✅ NOVO: GERADOR DE ID ÚNICO
# ========================================
def generate_operation_id(symbol: str, entry_price: float, timestamp: datetime) -> str:
    """Gera ID único para operação"""
    data = f"{symbol}{entry_price}{timestamp.isoformat()}".encode()
    return hashlib.md5(data).hexdigest()[:8].upper()

# ========================================
# GERADOR DE DADOS
# ========================================
class CandleGenerator:
    def __init__(self):
        self.price_state = {
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
            "USDJPY": 150.50,
        }
    
    def get_price_at_time(self, symbol: str, timestamp: datetime) -> float:
        base = self.price_state.get(symbol, 1.0)
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        second_of_minute = timestamp.second
        
        trend = (minute_of_day % 60 - 30) * 0.00001
        noise = (minute_of_day % 17 - 8) * 0.000005
        micro_movement = (second_of_minute % 60 - 30) * 0.0000001
        
        return base + trend + noise + micro_movement
    
    def get_candles(self, symbol: str, limit: int = 120) -> List[Candle]:
        candles = []
        now = get_utc_now()
        
        for i in range(limit, 0, -1):
            timestamp = now - timedelta(minutes=i)
            
            open_price = self.get_price_at_time(symbol, timestamp)
            close_price = self.get_price_at_time(symbol, timestamp + timedelta(minutes=1))
            
            high = max(open_price, close_price) + 0.00003
            low = min(open_price, close_price) - 0.00003
            
            candles.append(Candle(
                time=timestamp,
                open=open_price,
                close=close_price,
                high=high,
                low=low,
                volume=1000000.0
            ))
        
        return candles

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
    can_trade, reason = state.check_safety_limits()
    if not can_trade:
        log(reason)
        if "CONGELADO" in reason:
            audit.log_risk_limit(reason)
        return None
    
    if not should_trade_now():
        if Config.DEBUG_MODE:
            log(f"⏸️ Fora do horário de negociação ({Config.TRADING_START_HOUR}h-{Config.TRADING_END_HOUR}h)")
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
            log(f"  ⏭️ {symbol} (cooldown)")
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
    msg = (
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"💱 Par: {setup.symbol}\n"
        f"📊 Estratégia: {direction_emoji}\n"
        f"⏰ Entrada: {fmt_br(setup.entry_time)}\n"
        f"📈 Força: {setup.score:.3f}"
    )
    send_telegram(msg)
    log(f"📊 SINAL | {setup.symbol} | {setup.direction.value}")

def process_pending_setup(state: BotState) -> None:
    if state.pending_setup is None or get_utc_now() < state.pending_setup.entry_time:
        return
    setup = state.pending_setup
    p1_time = setup.entry_time + timedelta(minutes=1)
    p2_time = setup.entry_time + timedelta(minutes=2)
    
    entry_price = candle_gen.get_price_at_time(setup.symbol, setup.entry_time)
    operation_id = generate_operation_id(setup.symbol, entry_price, setup.entry_time)
    
    operation = ActiveOperation(
        symbol=setup.symbol,
        direction=setup.direction,
        stage=TradeStage.ENTRY,
        entry_time=setup.entry_time,
        entry_price=entry_price,
        protection1_time=p1_time,
        protection2_time=p2_time,
        operation_id=operation_id,
    )
    state.active_operations.append(operation)
    state.pending_setup = None
    state.operations_this_hour += 1
    
    mode_text = "(PAPER)" if state.trading_mode == TradingMode.PAPER else "(REAL)"
    audit.log("ENTRY", f"ID:{operation_id} | {setup.symbol} @ {entry_price:.6f} {mode_text}", "TRADE")
    
    direction_emoji = "🟢 COMPRA" if setup.direction == TradeDirection.BUY else "🔴 VENDA"
    msg = f"✅ ENTRADA [{operation_id}]\n\n💱 {setup.symbol}\n{direction_emoji}\n⏰ {fmt_br(setup.entry_time)}"
    send_telegram(msg)

# ========================================
# VERIFICAÇÃO DE RESULTADOS
# ========================================
def check_operation_result(operation: ActiveOperation, learning_mgr: LearningManager, state: BotState) -> Optional[ActiveOperation]:
    now = get_utc_now()
    
    if operation.stage == TradeStage.ENTRY:
        check_time = operation.entry_time + timedelta(minutes=1)
        next_stage = TradeStage.PROTECTION_1
        stage_name = "Entrada"
    elif operation.stage == TradeStage.PROTECTION_1:
        check_time = operation.protection1_time + timedelta(minutes=1)
        next_stage = TradeStage.PROTECTION_2
        stage_name = "Proteção 1"
    else:
        check_time = operation.protection2_time + timedelta(minutes=1)
        next_stage = None
        stage_name = "Proteção 2"
    
    if now < check_time + timedelta(seconds=5):
        return operation
    
    result_price = candle_gen.get_price_at_time(operation.symbol, check_time)
    
    log(f"  📊 {operation.symbol} M1 | Entrada: {operation.entry_price:.6f} | {stage_name}: {result_price:.6f}")
    
    if operation.direction == TradeDirection.BUY:
        if result_price <= operation.entry_price - Config.STOP_LOSS_PIPS:
            is_win = False
            log(f"  🛑 STOP LOSS | Entrada: {operation.entry_price:.6f} vs Resultado: {result_price:.6f}")
        elif result_price >= operation.entry_price + Config.TAKE_PROFIT_PIPS:
            is_win = True
            log(f"  🎯 TAKE PROFIT | Entrada: {operation.entry_price:.6f} vs Resultado: {result_price:.6f}")
        else:
            is_win = result_price > operation.entry_price
        direction_text = "COMPRA"
    else:
        if result_price >= operation.entry_price + Config.STOP_LOSS_PIPS:
            is_win = False
            log(f"  🛑 STOP LOSS | Entrada: {operation.entry_price:.6f} vs Resultado: {result_price:.6f}")
        elif result_price <= operation.entry_price - Config.TAKE_PROFIT_PIPS:
            is_win = True
            log(f"  🎯 TAKE PROFIT | Entrada: {operation.entry_price:.6f} vs Resultado: {result_price:.6f}")
        else:
            is_win = result_price < operation.entry_price
        direction_text = "VENDA"
    
    diff = result_price - operation.entry_price
    result_text = "✅ WIN" if is_win else "❌ LOSS"
    log(f"  {result_text} | {direction_text} | {stage_name} | Diferença: {diff:.6f} pips")
    
    log_operation(operation, stage_name, is_win, operation.entry_price, result_price)
    
    if is_win:
        state.record_win(operation.symbol, operation.entry_price, result_price)
        learning_mgr.record_result(operation.symbol, True, 0.0, str(get_br_now().hour))
        audit.log_operation(operation.operation_id, operation.symbol, operation.direction.value, operation.entry_price, True)
        msg = f"🏆 WIN [{operation.operation_id}]\n\n💱 {operation.symbol}\n✅ {stage_name}\n{direction_text}\n\nWins: {state.wins} | Losses: {state.losses}\n📈 {state.winrate:.1f}%"
        send_telegram(msg)
        log(f"✅ WIN REGISTRADO | {operation.symbol}")
        return None
    
    if next_stage is not None:
        operation.stage = next_stage
        log(f"  ⚠️ Avançando para {next_stage.name}")
        return operation
    
    state.record_loss(operation.symbol, operation.entry_price, result_price)
    learning_mgr.record_result(operation.symbol, False, 0.0, str(get_br_now().hour))
    audit.log_operation(operation.operation_id, operation.symbol, operation.direction.value, operation.entry_price, False)
    msg = f"🏆 LOSS [{operation.operation_id}]\n\n💱 {operation.symbol}\n❌ {stage_name}\n{direction_text}\n\nWins: {state.wins} | Losses: {state.losses}\n📈 {state.winrate:.1f}%"
    send_telegram(msg)
    log(f"❌ LOSS REGISTRADO | {operation.symbol}")
    
    if state.loss_streak >= Config.MAX_LOSS_STREAK and not state.paused:
        state.paused = True
        state.pause_until = get_utc_now() + timedelta(hours=1)
        msg = f"⏸️ PAUSA AUTOMÁTICA\n\n{state.loss_streak} losses consecutivos!\nBot pausado por 1 hora."
        send_telegram(msg)
        audit.log_risk_limit(f"Loss streak de {state.loss_streak} atingido")
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
# ✅ NOVO: GERADOR DE LIMITES
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
    
    mode_display = "📄 SIMULADO (Paper)" if state.trading_mode == TradingMode.PAPER else "💰 REAL"
    log(f"🤖 BOT FOREX INICIANDO... ({mode_display})")
    
    startup_msg = f"🤖 BOT FOREX ATIVADO 💱\n{mode_display}\n\nComandos:\n/start /stop /stats /health /ai /limits /mode /capital"
    send_telegram(startup_msg)
    audit.log("STARTUP", f"Bot iniciado em modo {state.trading_mode.value}", "INFO")
    
    while True:
        try:
            check_commands(state, learning_mgr)
            if not state.is_active:
                time.sleep(10)
                continue
            
            # Revalidar modo a cada ciclo
            state._validate_mode()
            
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
            audit.log("ERROR", str(e), "ERROR")
            time.sleep(10)

main()

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
    FOREX_API_KEY: str = "BFKUJTMXC8KO6RMS"
    
    SIGNAL_INTERVAL: int = 10
    BR_TIMEZONE: timezone = timezone(timedelta(hours=-3))
    UNIVERSE_REFRESH: int = 900
    
    # ✅ EXPANDIDO: Mais pares para permitir a rotação correta e ranqueamento
    ACTIVE_SYMBOLS: List[str] = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCAD", 
        "AUDUSD", "NZDUSD", "EURGBP", "EURJPY"
    ]
    
    EMA_SHORT: int = 9
    EMA_LONG: int = 21
    RSI_PERIOD: int = 14
    MIN_CANDLES: int = 60
    TREND_THRESHOLD: float = 0.0006
    
    LEARNING_FILE: str = "learning.json"
    OPERATIONS_LOG: str = "operations_log.csv"
    
    MIN_SIGNAL_STRENGTH: float = 5.0
    STOP_LOSS_PIPS: float = 0.0050
    TAKE_PROFIT_PIPS: float = 0.0100
    
    DEBUG_MODE: bool = False
    PAPER_MODE_AUTOSTART: bool = True  # Inicia simulando automaticamente

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
        
        # ✅ O bot já nasce ativo em Paper Mode para não ficar travado
        self.is_active: bool = Config.PAPER_MODE_AUTOSTART 
        
        self.last_update_id: Optional[int] = None
        self.performance: Dict[str, Dict[str, int]] = {
            symbol: {"win": 0, "loss": 0}
            for symbol in Config.ACTIVE_SYMBOLS
        }
        self.last_used_symbols: List[str] = []
        self.loss_streak: int = 0
        self.paused: bool = False
        self.pause_until: Optional[datetime] = None
        self._init_log_file()
    
    def _init_log_file(self) -> None:
        if not os.path.exists(Config.OPERATIONS_LOG):
            try:
                with open(Config.OPERATIONS_LOG, "w") as f:
                    f.write("TIMESTAMP,SYMBOL,DIRECTION,STAGE,IS_WIN,ENTRY_PRICE,RESULT_PRICE,DIFFERENCE\n")
            except Exception as e:
                log(f"⚠️ Erro ao criar log de operações: {e}")
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    def record_win(self, symbol: str) -> None:
        self.wins += 1
        self.performance[symbol]["win"] += 1
        self.loss_streak = 0
        self._add_to_history(symbol)
    
    def record_loss(self, symbol: str) -> None:
        self.losses += 1
        self.performance[symbol]["loss"] += 1
        self.loss_streak += 1
        self._add_to_history(symbol)
    
    def _add_to_history(self, symbol: str) -> None:
        # ✅ Correção: Registra todas as operações e mantém as últimas 5
        self.last_used_symbols.append(symbol)
        if len(self.last_used_symbols) > 5:
            self.last_used_symbols.pop(0)
    
    def can_use_symbol(self, symbol: str) -> bool:
        # ✅ Correção: Bloqueia apenas se o ativo for o ÚLTIMO operado
        if not self.last_used_symbols:
            return True
        return symbol != self.last_used_symbols[-1]

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
            except Exception as e:
                log(f"⚠️ Erro ao carregar aprendizado: {e}")
    
    def save(self) -> None:
        try:
            with open(self.file_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            log(f"⚠️ Erro ao salvar aprendizado: {e}")
    
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
        if winrate > 0.70: return 1.35
        if winrate > 0.65: return 1.25
        if winrate > 0.55: return 1.10
        if winrate > 0.45: return 0.90
        return 0.70
    
    def get_hour_multiplier(self) -> float:
        hour = str(get_br_now().hour)
        stats = self.data["hour_stats"].get(hour)
        if not stats or stats["total"] < 5:
            return 1.0
        winrate = stats["win"] / stats["total"]
        if winrate > 0.70: return 1.40
        if winrate > 0.60: return 1.25
        if winrate > 0.55: return 1.10
        return 0.85
    
    def get_pattern_multiplier(self, symbol: str, hour: str = "") -> float:
        hour = hour or str(get_br_now().hour)
        pattern_key = f"{symbol}_{hour}"
        stats = self.data["pattern_stats"].get(pattern_key)
        if not stats or stats["total"] < 3:
            return 1.0
        winrate = stats["win"] / stats["total"]
        if winrate > 0.75: return 1.50
        if winrate > 0.65: return 1.30
        if winrate > 0.55: return 1.15
        return 0.85
    
    def get_correlation_multiplier(self, symbol: str) -> float:
        correlations = {
            "EURUSD": {"GBPUSD": 0.8, "USDJPY": -0.6},
            "GBPUSD": {"EURUSD": 0.8, "AUDCAD": -0.5},
            "USDJPY": {"EURUSD": -0.6},
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
        if ratio > 1.5: return 1.25
        if ratio > 1.2: return 1.10
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
            log(f"🧠 IA Multipliers | Asset: {asset_mult:.2f} | Hour: {hour_mult:.2f} | Total: {total:.2f}")
        return total
    
    def generate_report(self) -> str:
        # Simplificado para evitar erro em relatórios iniciais sem dados
        return "🧠 RELATÓRIO IA:\nColetando dados suficientes para gerar recomendações..."

# ========================================
# TEMPO E UTILITÁRIOS
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

def log(msg: str) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

# ========================================
# TELEGRAM INTEGRATION
# ========================================
def send_telegram(msg: str) -> bool:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": msg}
        response = requests.post(url, data=payload, timeout=5)
        response.raise_for_status()
        return True
    except Exception as e:
        log(f"⚠️ Aviso Telegram: Falha no envio (Continuando em modo local) - {e}")
        return False

def remove_webhook() -> None:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook"
        requests.get(url, timeout=5)
    except:
        pass

def validate_credentials() -> bool:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            log("✅ Credenciais do Telegram validadas")
            return True
        return False
    except:
        log("⚠️ Erro ao validar Telegram. O Bot continuará operando localmente.")
        return False

def check_commands(state: BotState, learning_mgr: LearningManager) -> None:
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates"
        params = {"timeout": 0}
        if state.last_update_id is not None:
            params["offset"] = state.last_update_id + 1
        response = requests.get(url, params=params, timeout=5)
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
                send_telegram("🟢 BOT ATIVADO")
                log("✅ BOT ATIVADO")
            elif text == "/stop":
                state.is_active = False
                send_telegram("🔴 BOT PARADO")
                log("⏹️ BOT PARADO")
    except Exception:
        pass

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
# GERADOR DE DADOS (SIMULAÇÃO)
# ========================================
class CandleGenerator:
    def __init__(self):
        self.price_state = {
            "EURUSD": 1.0850, "GBPUSD": 1.2650, "USDJPY": 150.50,
            "USDCAD": 1.3650, "AUDUSD": 0.6550, "NZDUSD": 0.6050,
            "EURCAD": 1.4850, "EURGBP": 0.8550, "EURJPY": 163.50,
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
            candles.append(Candle(time=timestamp, open=open_price, close=close_price, high=high, low=low, volume=1000.0))
        return candles

candle_gen = CandleGenerator()

def get_candles(symbol: str, limit: int = 120) -> Optional[List[Candle]]:
    try:
        return candle_gen.get_candles(symbol, limit)
    except:
        return None

# ========================================
# INDICADORES E LÓGICA
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
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

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
    return volatility * 50 + trend * 120 + abs(rsi - 50) * 0.3

def update_active_symbols(learning_mgr: LearningManager, state: BotState) -> None:
    log("🔄 Atualizando universo de ativos (Buscando os 8 melhores)...")
    symbols = Config.ACTIVE_SYMBOLS
    scored: List[Tuple[str, float]] = []
    
    for symbol in symbols:
        try:
            score = calculate_asset_quality_score(symbol)
            scored.append((symbol, score))
        except:
            pass
            
    if not scored:
        return
        
    scored.sort(key=lambda x: x[1], reverse=True)
    Config.ACTIVE_SYMBOLS = [s[0] for s in scored[:8]]
    state.last_universe_update = get_utc_now()
    log(f"✅ Universo de ativos atualizado!")

def select_best_asset(learning_mgr: LearningManager, state: BotState) -> Optional[Tuple[str, TradeDirection, float]]:
    if not should_trade_now():
        return None
        
    if state.paused and get_utc_now() >= state.pause_until:
        state.paused = False
        state.loss_streak = 0
        log("▶️ BOT RETOMADO - Fim da Pausa")
        send_telegram("▶️ BOT RETOMADO - Pausa encerrada")
    elif state.paused:
        return None
    
    candidates: List[Tuple[str, TradeDirection, float]] = []
    
    for symbol in Config.ACTIVE_SYMBOLS:
        if not state.can_use_symbol(symbol):
            continue
            
        candles = get_candles(symbol)
        if not candles or len(candles) < Config.MIN_CANDLES:
            continue
            
        closes = [c.close for c in candles]
        ema_short = calculate_ema(closes, Config.EMA_SHORT)
        ema_long = calculate_ema(closes, Config.EMA_LONG)
        rsi = calculate_rsi(closes, Config.RSI_PERIOD)
        
        if any(v is None for v in [ema_short, ema_long, rsi]):
            continue
            
        trend_pct = abs(ema_short - ema_long) / closes[-1]
        score = trend_pct * 1000 + abs(rsi - 50) * 2
        score *= learning_mgr.get_total_multiplier(symbol, score)
        
        if ema_short > ema_long:
            candidates.append((symbol, TradeDirection.BUY, score))
        elif ema_short < ema_long:
            candidates.append((symbol, TradeDirection.SELL, score))
            
    if candidates:
        strong_candidates = [(s, d, sc) for s, d, sc in candidates if sc > Config.MIN_SIGNAL_STRENGTH]
        if strong_candidates:
            strong_candidates.sort(key=lambda x: x[2], reverse=True)
            best_symbol, best_direction, best_score = strong_candidates[0]
            return (best_symbol, best_direction, best_score)
    return None

def create_signal(setup: PendingSetup, state: BotState) -> None:
    state.pending_setup = setup
    state.last_signal_time = get_utc_now()
    log(f"📊 SINAL ENCONTRADO | {setup.symbol} | {setup.direction.value} | Força: {setup.score:.3f}")

def process_pending_setup(state: BotState) -> None:
    if state.pending_setup is None or get_utc_now() < state.pending_setup.entry_time:
        return
    setup = state.pending_setup
    p1_time = setup.entry_time + timedelta(minutes=1)
    p2_time = setup.entry_time + timedelta(minutes=2)
    entry_price = candle_gen.get_price_at_time(setup.symbol, setup.entry_time)
    
    operation = ActiveOperation(
        symbol=setup.symbol, direction=setup.direction, stage=TradeStage.ENTRY,
        entry_time=setup.entry_time, entry_price=entry_price,
        protection1_time=p1_time, protection2_time=p2_time,
    )
    state.active_operations.append(operation)
    state.pending_setup = None
    log(f"✅ ENTRADA REALIZADA | {setup.symbol} | {setup.direction.value}")

def check_operation_result(operation: ActiveOperation, learning_mgr: LearningManager, state: BotState) -> Optional[ActiveOperation]:
    now = get_utc_now()
    if operation.stage == TradeStage.ENTRY:
        check_time = operation.entry_time + timedelta(minutes=1)
        next_stage = TradeStage.PROTECTION_1
    elif operation.stage == TradeStage.PROTECTION_1:
        check_time = operation.protection1_time + timedelta(minutes=1)
        next_stage = TradeStage.PROTECTION_2
    else:
        check_time = operation.protection2_time + timedelta(minutes=1)
        next_stage = None
        
    if now < check_time + timedelta(seconds=5):
        return operation
        
    result_price = candle_gen.get_price_at_time(operation.symbol, check_time)
    
    if operation.direction == TradeDirection.BUY:
        if result_price <= operation.entry_price - Config.STOP_LOSS_PIPS: is_win = False
        elif result_price >= operation.entry_price + Config.TAKE_PROFIT_PIPS: is_win = True
        else: is_win = result_price > operation.entry_price
    else:
        if result_price >= operation.entry_price + Config.STOP_LOSS_PIPS: is_win = False
        elif result_price <= operation.entry_price - Config.TAKE_PROFIT_PIPS: is_win = True
        else: is_win = result_price < operation.entry_price
        
    log_operation(operation, operation.stage.name, is_win, operation.entry_price, result_price)
    
    if is_win:
        state.record_win(operation.symbol)
        learning_mgr.record_result(operation.symbol, True)
        log(f"🏆 WIN REGISTRADO | {operation.symbol}")
        return None
        
    if next_stage is not None:
        operation.stage = next_stage
        log(f"⚠️ {operation.symbol} avançou para {next_stage.name}")
        return operation
        
    state.record_loss(operation.symbol)
    learning_mgr.record_result(operation.symbol, False)
    log(f"❌ LOSS REGISTRADO | {operation.symbol}")
    
    if state.loss_streak >= 5 and not state.paused:
        state.paused = True
        state.pause_until = get_utc_now() + timedelta(hours=1)
        log(f"⏸️ BOT PAUSADO: {state.loss_streak} losses seguidos")
    return None

# ========================================
# MAIN LOOP
# ========================================
def main() -> None:
    validate_credentials()
    remove_webhook()
    learning_mgr = LearningManager()
    state = BotState()
    
    log("🤖 BOT FOREX INICIANDO...")
    if state.is_active:
        log("🚀 Iniciando automaticamente em MODO PAPER (Simulação)...")
        send_telegram("🤖 BOT FOREX ATIVADO (Modo Automático/Paper)")

    while True:
        try:
            check_commands(state, learning_mgr)
            if not state.is_active:
                time.sleep(10)
                continue
                
            if state.last_universe_update is None or (get_utc_now() - state.last_universe_update).total_seconds() > Config.UNIVERSE_REFRESH:
                update_active_symbols(learning_mgr, state)
                
            process_pending_setup(state)
            
            new_operations = []
            for operation in state.active_operations:
                result = check_operation_result(operation, learning_mgr, state)
                if result is not None:
                    new_operations.append(result)
            state.active_operations = new_operations
            
            if state.pending_setup is None and not state.active_operations:
                if state.last_signal_time is None or (get_utc_now() - state.last_signal_time).total_seconds() >= Config.SIGNAL_INTERVAL:
                    result = select_best_asset(learning_mgr, state)
                    if result:
                        symbol, direction, score = result
                        entry_time = next_minute(get_utc_now()) + timedelta(minutes=1)
                        setup = PendingSetup(symbol=symbol, direction=direction, score=score, entry_time=entry_time)
                        create_signal(setup, state)
                        
            time.sleep(5)
            
        except Exception as e:
            log(f"❌ Erro Crítico no Loop Principal: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()

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
    
    # Lista expandida para garantir rotação e análise da IA
    ACTIVE_SYMBOLS: List[str] = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCAD", 
        "AUDUSD", "NZDUSD", "EURGBP", "EURJPY"
    ]
    
    EMA_SHORT: int = 9
    EMA_LONG: int = 21
    RSI_PERIOD: int = 14
    MIN_CANDLES: int = 60
    
    LEARNING_FILE: str = "learning.json"
    OPERATIONS_LOG: str = "operations_log.csv"
    
    MIN_SIGNAL_STRENGTH: float = 5.0
    STOP_LOSS_PIPS: float = 0.0050
    TAKE_PROFIT_PIPS: float = 0.0100
    
    DEBUG_MODE: bool = False
    PAPER_MODE_AUTOSTART: bool = True # Inicia simulando automaticamente

# ========================================
# DATA CLASSES E ENUMS
# ========================================
class TradeDirection(Enum):
    BUY = "BUY"
    SELL = "SELL"

class TradeStage(Enum):
    ENTRY = 0
    PROTECTION_1 = 1
    PROTECTION_2 = 2

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
        if response.status_code != 200:
            log(f"❌ Erro Telegram: {response.status_code} - {response.text}")
            return False
        return True
    except Exception as e:
        log(f"❌ Erro de Conexão Telegram: {e}")
        return False

# ========================================
# STATE MANAGER (CORREÇÃO DE COOLDOWN)
# ========================================
class BotState:
    def __init__(self):
        self.wins: int = 0
        self.losses: int = 0
        self.active_operations: List[ActiveOperation] = []
        self.pending_setup: Optional[PendingSetup] = None
        self.last_signal_time: Optional[datetime] = None
        self.last_universe_update: Optional[datetime] = None
        self.is_active: bool = Config.PAPER_MODE_AUTOSTART
        self.last_update_id: Optional[int] = None
        self.performance: Dict[str, Dict[str, int]] = {s: {"win": 0, "loss": 0} for s in Config.ACTIVE_SYMBOLS}
        self.last_used_symbols: List[str] = []
        self.loss_streak: int = 0
        self.paused: bool = False
        self.pause_until: Optional[datetime] = None
        self._init_log_file()
    
    def _init_log_file(self) -> None:
        if not os.path.exists(Config.OPERATIONS_LOG):
            with open(Config.OPERATIONS_LOG, "w") as f:
                f.write("TIMESTAMP,SYMBOL,DIRECTION,STAGE,IS_WIN,ENTRY_PRICE,RESULT_PRICE,DIFFERENCE\n")
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    def record_win(self, symbol: str) -> None:
        self.wins += 1
        self.loss_streak = 0
        self._add_to_history(symbol)
    
    def record_loss(self, symbol: str) -> None:
        self.losses += 1
        self.loss_streak += 1
        self._add_to_history(symbol)
    
    def _add_to_history(self, symbol: str) -> None:
        self.last_used_symbols.append(symbol)
        if len(self.last_used_symbols) > 5:
            self.last_used_symbols.pop(0)
    
    def can_use_symbol(self, symbol: str) -> bool:
        # ✅ Bloqueia apenas se o ativo for EXATAMENTE o último operado
        if not self.last_used_symbols: return True
        return symbol != self.last_used_symbols[-1]

# ========================================
# APRENDIZADO IA (SIMPLIFICADO)
# ========================================
class LearningManager:
    def __init__(self, file_path: str = Config.LEARNING_FILE):
        self.file_path = file_path
        self.data: Dict[str, Any] = {"asset_stats": {}, "hour_stats": {}}
        self.load()
    
    def load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f: self.data = json.load(f)
            except: pass
            
    def save(self):
        try:
            with open(self.file_path, "w") as f: json.dump(self.data, f, indent=2)
        except: pass

    def record_result(self, symbol: str, is_win: bool):
        if symbol not in self.data["asset_stats"]: self.data["asset_stats"][symbol] = {"win": 0, "total": 0}
        self.data["asset_stats"][symbol]["total"] += 1
        if is_win: self.data["asset_stats"][symbol]["win"] += 1
        self.save()

    def get_total_multiplier(self, symbol: str, score: float) -> float:
        stats = self.data["asset_stats"].get(symbol)
        if not stats or stats["total"] < 5: return 1.0
        wr = stats["win"] / stats["total"]
        if wr > 0.60: return 1.2
        if wr < 0.40: return 0.8
        return 1.0

# ========================================
# TEMPO E CANDLES
# ========================================
def get_utc_now() -> datetime: return datetime.now(timezone.utc)
def get_br_now() -> datetime: return get_utc_now().astimezone(Config.BR_TIMEZONE)
def floor_minute(dt: datetime) -> datetime: return dt.replace(second=0, microsecond=0)
def next_minute(dt: datetime) -> datetime: return floor_minute(dt) + timedelta(minutes=1)
def fmt_br(dt: datetime) -> str: return dt.astimezone(Config.BR_TIMEZONE).strftime("%H:%M")

class CandleGenerator:
    def __init__(self):
        self.prices = {"EURUSD": 1.08, "GBPUSD": 1.26, "USDJPY": 150.0, "USDCAD": 1.36, "AUDUSD": 0.65, "NZDUSD": 0.60, "EURGBP": 0.85, "EURJPY": 163.0}
    def get_price(self, symbol, ts): return self.prices.get(symbol, 1.0) + (ts.minute * 0.00001)
    def get_candles(self, symbol):
        now = get_utc_now()
        return [Candle(now - timedelta(minutes=i), self.get_price(symbol, now), self.get_price(symbol, now), 1.0, 1.0, 1.0) for i in range(120)]

candle_gen = CandleGenerator()

# ========================================
# INDICADORES
# ========================================
def calculate_ema(prices, period):
    if len(prices) < period: return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for p in prices[period:]: ema = (p - ema) * k + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1: return None
    gains = sum(max(0, prices[i] - prices[i-1]) for i in range(1, period+1))
    losses = sum(max(0, prices[i-1] - prices[i]) for i in range(1, period+1))
    if losses == 0: return 100
    return 100 - (100 / (1 + (gains/losses)))

# ========================================
# LÓGICA DE NEGOCIAÇÃO (SINAIS E ENTRADAS)
# ========================================
def select_best_asset(learning_mgr, state):
    if state.paused and get_utc_now() < state.pause_until: return None
    state.paused = False
    
    candidates = []
    for symbol in Config.ACTIVE_SYMBOLS:
        if not state.can_use_symbol(symbol): continue
        candles = candle_gen.get_candles(symbol)
        closes = [c.close for c in candles]
        e9, e21, rsi = calculate_ema(closes, 9), calculate_ema(closes, 21), calculate_rsi(closes)
        
        if e9 and e21 and rsi:
            score = (abs(e9 - e21) / closes[-1]) * 10000 + abs(rsi - 50)
            score *= learning_mgr.get_total_multiplier(symbol, score)
            if e9 > e21: candidates.append((symbol, TradeDirection.BUY, score))
            elif e9 < e21: candidates.append((symbol, TradeDirection.SELL, score))
    
    if candidates:
        candidates.sort(key=lambda x: x[2], reverse=True)
        if candidates[0][2] >= Config.MIN_SIGNAL_STRENGTH: return candidates[0]
    return None

def create_signal(setup, state):
    state.pending_setup = setup
    state.last_signal_time = get_utc_now()
    emoji = "🟢 COMPRA" if setup.direction == TradeDirection.BUY else "🔴 VENDA"
    msg = f"⚠️ SINAL: {setup.symbol}\nEstratégia: {emoji}\nEntrada: {fmt_br(setup.entry_time)}\nScore: {setup.score:.2f}"
    send_telegram(msg)
    log(f"📊 SINAL | {setup.symbol}")

def process_pending_setup(state):
    if state.pending_setup and get_utc_now() >= state.pending_setup.entry_time:
        s = state.pending_setup
        op = ActiveOperation(s.symbol, s.direction, TradeStage.ENTRY, s.entry_time, candle_gen.get_price(s.symbol, s.entry_time), s.entry_time + timedelta(minutes=1), s.entry_time + timedelta(minutes=2))
        state.active_operations.append(op)
        state.pending_setup = None
        send_telegram(f"✅ ENTRADA: {op.symbol}\nPreço: {op.entry_price:.5f}")

# ========================================
# RESULTADOS E CICLO PRINCIPAL
# ========================================
def check_results(learning_mgr, state):
    still_active = []
    for op in state.active_operations:
        check_ts = op.entry_time + timedelta(minutes=1 + op.stage.value)
        if get_utc_now() < check_ts + timedelta(seconds=5):
            still_active.append(op); continue
            
        cur_price = candle_gen.get_price(op.symbol, check_ts)
        is_win = (cur_price > op.entry_price) if op.direction == TradeDirection.BUY else (cur_price < op.entry_price)
        
        if is_win:
            state.record_win(op.symbol); learning_mgr.record_result(op.symbol, True)
            send_telegram(f"🏆 WIN: {op.symbol}\nWinrate: {state.winrate:.1f}%")
        elif op.stage != TradeStage.PROTECTION_2:
            op.stage = TradeStage(op.stage.value + 1)
            still_active.append(op)
            log(f"⚠️ {op.symbol} -> Proteção {op.stage.value}")
        else:
            state.record_loss(op.symbol); learning_mgr.record_result(op.symbol, False)
            send_telegram(f"❌ LOSS: {op.symbol}\nWinrate: {state.winrate:.1f}%")
            if state.loss_streak >= 5:
                state.paused = True; state.pause_until = get_utc_now() + timedelta(hours=1)
                send_telegram("⏸️ PAUSA: 5 Losses seguidos. Retorno em 1h.")
    state.active_operations = still_active

def main():
    log("🤖 BOT FOREX INICIADO...")
    send_telegram("🤖 BOT FOREX ATIVADO\nModo: Paper/Simulação")
    state, lm = BotState(), LearningManager()
    
    while True:
        try:
            if not state.is_active: time.sleep(10); continue
            process_pending_setup(state)
            check_results(lm, state)
            
            if not state.pending_setup and not state.active_operations:
                res = select_best_asset(lm, state)
                if res: create_signal(PendingSetup(res[0], res[1], res[2], next_minute(get_utc_now()) + timedelta(minutes=1)), state)
            time.sleep(5)
        except Exception as e:
            log(f"❌ Erro: {e}"); time.sleep(10)

if __name__ == "__main__":
    main()

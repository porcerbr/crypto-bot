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
    
    ACTIVE_SYMBOLS: List[str] = [
        "EURUSD", "GBPUSD", "USDJPY", "USDCAD",
        "AUDUSD", "NZDUSD", "EURCAD", "EURGBP",
        "EURJPY", "GBPJPY", "AUDCAD", "AUDCHF"
    ]
    
    EMA_SHORT: int = 9
    EMA_LONG: int = 21
    RSI_PERIOD: int = 14
    MIN_CANDLES: int = 60
    TREND_THRESHOLD: float = 0.0006
    
    LEARNING_FILE: str = "learning.json"

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
    
    @property
    def winrate(self) -> float:
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    def record_win(self, symbol: str) -> None:
        self.wins += 1
        self.performance[symbol]["win"] += 1
        self._add_to_history(symbol)
    
    def record_loss(self, symbol: str) -> None:
        self.losses += 1
        self.performance[symbol]["loss"] += 1
        self._add_to_history(symbol)
    
    def _add_to_history(self, symbol: str) -> None:
        """Adiciona símbolo ao histórico e mantém últimos 5"""
        if symbol not in self.last_used_symbols:
            self.last_used_symbols.append(symbol)
        if len(self.last_used_symbols) > 5:
            self.last_used_symbols.pop(0)
    
    def can_use_symbol(self, symbol: str) -> bool:
        """Verifica se pode usar o símbolo (evita repetição)"""
        return symbol not in self.last_used_symbols[:3]

# ========================================
# APRENDIZADO
# ========================================
class LearningManager:
    def __init__(self, file_path: str = Config.LEARNING_FILE):
        self.file_path = file_path
        self.data: Dict[str, Any] = {"asset_stats": {}, "hour_stats": {}}
        self.load()
    
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
    
    def record_result(self, symbol: str, is_win: bool) -> None:
        hour = str(get_br_now().hour)
        if symbol not in self.data["asset_stats"]:
            self.data["asset_stats"][symbol] = {"win": 0, "loss": 0}
        key = "win" if is_win else "loss"
        self.data["asset_stats"][symbol][key] += 1
        if hour not in self.data["hour_stats"]:
            self.data["hour_stats"][hour] = {"win": 0, "loss": 0}
        self.data["hour_stats"][hour][key] += 1
        self.save()
    
    def get_asset_multiplier(self, symbol: str) -> float:
        stats = self.data["asset_stats"].get(symbol)
        if not stats:
            return 1.0
        total = stats["win"] + stats["loss"]
        if total < 5:
            return 1.0
        winrate = stats["win"] / total
        return 1.2 if winrate > 0.65 else (0.8 if winrate < 0.40 else 1.0)
    
    def get_hour_multiplier(self) -> float:
        hour = str(get_br_now().hour)
        stats = self.data["hour_stats"].get(hour)
        if not stats:
            return 1.0
        total = stats["win"] + stats["loss"]
        if total < 5:
            return 1.0
        winrate = stats["win"] / total
        return 1.15 if winrate > 0.65 else (0.85 if winrate < 0.40 else 1.0)

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
# COMANDOS TELEGRAM
# ========================================
def check_commands(state: BotState) -> None:
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
                send_telegram("🟢 BOT ATIVADO")
                log("✅ BOT ATIVADO")
            elif text == "/stop":
                state.is_active = False
                send_telegram("🔴 BOT PARADO")
                log("⏹️ BOT PARADO")
            elif text == "/stats":
                send_telegram(
                    f"📊 ESTATÍSTICAS\n\n"
                    f"✅ Wins: {state.wins}\n"
                    f"❌ Losses: {state.losses}\n"
                    f"📈 Winrate: {state.winrate:.1f}%\n"
                    f"🎯 Operações: {len(state.active_operations)}\n"
                    f"📋 Últimos: {', '.join(state.last_used_symbols[-3:]) if state.last_used_symbols else 'Nenhum'}"
                )
    except Exception as e:
        log(f"❌ Erro comandos: {e}")

# ========================================
# GERADOR DE DADOS - EVOLUINDO COM TEMPO
# ========================================
class CandleGenerator:
    """Gera candles que evoluem com o tempo real"""
    def __init__(self):
        self.price_state = {
            "EURUSD": 1.0850,
            "GBPUSD": 1.2650,
            "USDJPY": 150.50,
            "USDCAD": 1.3650,
            "AUDUSD": 0.6550,
            "NZDUSD": 0.6050,
            "EURCAD": 1.4850,
            "EURGBP": 0.8550,
            "EURJPY": 163.50,
            "GBPJPY": 190.50,
            "AUDCAD": 0.9350,
            "AUDCHF": 0.6150,
        }
    
    def get_price_at_time(self, symbol: str, timestamp: datetime) -> float:
        """Retorna preço simulado em um momento específico"""
        base = self.price_state.get(symbol, 1.0)
        minute_of_day = timestamp.hour * 60 + timestamp.minute
        second_of_minute = timestamp.second
        
        # Movimento principal: sobe e desce ao longo do dia
        trend = (minute_of_day % 60 - 30) * 0.00001
        
        # Movimento secundário: oscilações
        noise = (minute_of_day % 17 - 8) * 0.000005
        
        # Movimento fino: baseado em segundos
        micro_movement = (second_of_minute % 60 - 30) * 0.0000001
        
        return base + trend + noise + micro_movement
    
    def get_candles(self, symbol: str, limit: int = 120) -> List[Candle]:
        """Gera candles com preços evoluindo"""
        candles = []
        now = get_utc_now()
        
        for i in range(limit, 0, -1):
            timestamp = now - timedelta(minutes=i)
            
            # Preço na abertura e fechamento
            open_price = self.get_price_at_time(symbol, timestamp)
            close_price = self.get_price_at_time(symbol, timestamp + timedelta(minutes=1))
            
            # High e Low
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

# Instância global do gerador
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
    Config.ACTIVE_SYMBOLS = [s[0] for s in scored[:8]]
    state.last_universe_update = get_utc_now()
    
    log(f"✅ Universo atualizado com 8 ativos:")
    for i, (symbol, score) in enumerate(scored[:8], 1):
        log(f"  {i}. {symbol} (score: {score:.3f})")

def select_best_asset(learning_mgr: LearningManager, state: BotState) -> Optional[Tuple[str, TradeDirection, float]]:
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
        
        perf_data = state.performance.get(symbol, {"win": 0, "loss": 0})
        total = perf_data["win"] + perf_data["loss"]
        
        if total >= 10:
            winrate = perf_data["win"] / total
            if winrate > 0.65:
                score *= 1.15
            elif winrate < 0.40:
                score *= 0.85
        
        score *= learning_mgr.get_asset_multiplier(symbol)
        score *= learning_mgr.get_hour_multiplier()
        
        log(f"    Trend: {trend_pct:.6f} | Score: {score:.3f}")
        
        # ✅ RELAXADO: Critério menos restritivo
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
        candidates.sort(key=lambda x: x[2], reverse=True)
        best_symbol, best_direction, best_score = candidates[0]
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
    operation = ActiveOperation(
        symbol=setup.symbol,
        direction=setup.direction,
        stage=TradeStage.ENTRY,
        entry_time=setup.entry_time,
        protection1_time=p1_time,
        protection2_time=p2_time,
    )
    state.active_operations.append(operation)
    state.pending_setup = None
    direction_emoji = "🟢 COMPRA" if setup.direction == TradeDirection.BUY else "🔴 VENDA"
    msg = f"✅ ENTRADA\n\n💱 {setup.symbol}\n{direction_emoji}\n⏰ {fmt_br(setup.entry_time)}"
    send_telegram(msg)

# ========================================
# VERIFICAÇÃO DE RESULTADOS
# ========================================
def check_operation_result(operation: ActiveOperation, learning_mgr: LearningManager, state: BotState) -> Optional[ActiveOperation]:
    """Verifica resultado da operação baseado em tempo real M1"""
    
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
    
    entry_price = candle_gen.get_price_at_time(operation.symbol, operation.entry_time)
    result_price = candle_gen.get_price_at_time(operation.symbol, check_time)
    
    log(f"  📊 {operation.symbol} M1 | Entrada: {entry_price:.6f} | {stage_name}: {result_price:.6f}")
    
    if operation.direction == TradeDirection.BUY:
        is_win = result_price > entry_price
        direction_text = "COMPRA"
    else:
        is_win = result_price < entry_price
        direction_text = "VENDA"
    
    diff = result_price - entry_price
    result_text = "✅ WIN" if is_win else "❌ LOSS"
    log(f"  {result_text} | {direction_text} | {stage_name} | Diferença: {diff:.6f} pips")
    
    if is_win:
        state.record_win(operation.symbol)
        learning_mgr.record_result(operation.symbol, True)
        msg = f"🏆 WIN\n\n💱 {operation.symbol}\n✅ {stage_name}\n{direction_text}\n\nWins: {state.wins} | Losses: {state.losses}\n📈 {state.winrate:.1f}%"
        send_telegram(msg)
        log(f"✅ WIN REGISTRADO | {operation.symbol}")
        return None
    
    if next_stage is not None:
        operation.stage = next_stage
        log(f"  ⚠️ Avançando para {next_stage.name}")
        return operation
    
    state.record_loss(operation.symbol)
    learning_mgr.record_result(operation.symbol, False)
    msg = f"🏆 LOSS\n\n💱 {operation.symbol}\n❌ {stage_name}\n{direction_text}\n\nWins: {state.wins} | Losses: {state.losses}\n📈 {state.winrate:.1f}%"
    send_telegram(msg)
    log(f"❌ LOSS REGISTRADO | {operation.symbol}")
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
    remove_webhook()
    learning_mgr = LearningManager()
    state = BotState()
    log("🤖 BOT FOREX INICIANDO...")
    send_telegram("🤖 BOT FOREX ATIVADO 💱")
    
    while True:
        try:
            check_commands(state)
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

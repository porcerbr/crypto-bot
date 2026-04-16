import os
import time
import requests
import json
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, Dict, List, Any
from dataclasses import dataclass, asdict
from enum import Enum

# ========================================
# ENUMERAÇÕES
# ========================================
class TradeDirection(Enum):
    """Direção da operação"""
    BUY = "BUY"
    SELL = "SELL"

class TradeStage(Enum):
    """Estágios da operação"""
    ENTRY = 0
    PROTECTION_1 = 1
    PROTECTION_2 = 2

# ========================================
# DATA CLASSES
# ========================================
@dataclass
class Candle:
    """Vela de preço"""
    time: datetime
    open: float
    close: float
    high: float
    low: float
    volume: float

@dataclass
class PendingSetup:
    """Setup pendente de entrada"""
    symbol: str
    direction: TradeDirection
    score: float
    entry_time: datetime

@dataclass
class ActiveOperation:
    """Operação ativa em execução"""
    symbol: str
    direction: TradeDirection
    stage: TradeStage
    entry_time: datetime
    protection1_time: datetime
    protection2_time: datetime

# ========================================
# CONFIGURAÇÕES
# ========================================
class Config:
    """Configurações centralizadas"""
    
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "7952260034:AAFAY9-cEIe9aqcWxmy9WR6_qP5Uxxn8RhQ")
    CHAT_ID: str = os.getenv("CHAT_ID", "1056795017")
    
    # Timing
    INTERVAL: str = "1m"
    SIGNAL_INTERVAL: int = 120
    BR_TIMEZONE: timezone = timezone(timedelta(hours=-3))
    UNIVERSE_REFRESH: int = 900
    
    # Pares Forex
    ACTIVE_SYMBOLS: List[str] = [
        "AUDCAD",   # AUD/CAD - 75%
        "AUDCHF",   # AUD/CHF - 59%
        "AUDJPY",   # AUD/JPY - 79%
        "AUDUSD",   # AUD/USD - 69%
        "EURAUD",   # EUR/AUD - 60%
        "EURCAD",   # EUR/CAD - 76%
        "EURGBP",   # EUR/GBP - 85%
        "EURJPY",   # EUR/JPY - 87%
        "EURUSD",   # EUR/USD - 82%
        "GBPAUD",   # GBP/AUD - 76%
        "GBPCAD",   # GBP/CAD - 76%
        "GBPCHF",   # GBP/CHF - 60%
        "GBPJPY",   # GBP/JPY - 70%
        "GBPUSD",   # GBP/USD - 70%
        "USDCAD",   # USD/CAD - 60%
        "USDCHF",   # USD/CHF - 60%
        "USDJPY",   # USD/JPY - ?
    ]
    
    # Indicadores
    EMA_SHORT: int = 9
    EMA_LONG: int = 21
    RSI_PERIOD: int = 14
    MIN_CANDLES: int = 60
    TREND_THRESHOLD: float = 0.0006
    
    # Arquivo de aprendizado
    LEARNING_FILE: str = "learning.json"
    
    @classmethod
    def validate(cls) -> bool:
        """Valida configurações críticas"""
        if not cls.BOT_TOKEN or not cls.CHAT_ID:
            raise ValueError(
                "❌ BOT_TOKEN e CHAT_ID não configurados. "
                "Use variáveis de ambiente."
            )
        return True

# ========================================
# STATE MANAGER
# ========================================
class BotState:
    """Gerencia estado do bot"""
    
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
    
    @property
    def winrate(self) -> float:
        """Calcula taxa de vitória"""
        total = self.wins + self.losses
        return (self.wins / total * 100) if total > 0 else 0.0
    
    def record_win(self, symbol: str) -> None:
        """Registra vitória"""
        self.wins += 1
        self.performance[symbol]["win"] += 1
    
    def record_loss(self, symbol: str) -> None:
        """Registra derrota"""
        self.losses += 1
        self.performance[symbol]["loss"] += 1

# ========================================
# APRENDIZADO
# ========================================
class LearningManager:
    """Gerencia aprendizado automático"""
    
    def __init__(self, file_path: str = Config.LEARNING_FILE):
        self.file_path = file_path
        self.data: Dict[str, Any] = {
            "asset_stats": {},
            "hour_stats": {}
        }
        self.load()
    
    def load(self) -> None:
        """Carrega dados de aprendizado"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r") as f:
                    self.data = json.load(f)
                log("✅ Aprendizado carregado")
            except Exception as e:
                log(f"⚠️ Erro ao carregar aprendizado: {e}")
    
    def save(self) -> None:
        """Salva dados de aprendizado"""
        try:
            with open(self.file_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            log(f"⚠️ Erro ao salvar aprendizado: {e}")
    
    def record_result(self, symbol: str, is_win: bool) -> None:
        """Registra resultado de operação"""
        hour = str(get_br_now().hour)
        
        # Asset stats
        if symbol not in self.data["asset_stats"]:
            self.data["asset_stats"][symbol] = {"win": 0, "loss": 0}
        
        key = "win" if is_win else "loss"
        self.data["asset_stats"][symbol][key] += 1
        
        # Hour stats
        if hour not in self.data["hour_stats"]:
            self.data["hour_stats"][hour] = {"win": 0, "loss": 0}
        
        self.data["hour_stats"][hour][key] += 1
        
        self.save()
    
    def get_asset_multiplier(self, symbol: str) -> float:
        """Retorna multiplicador baseado em histórico do ativo"""
        stats = self.data["asset_stats"].get(symbol)
        if not stats:
            return 1.0
        
        total = stats["win"] + stats["loss"]
        if total < 5:
            return 1.0
        
        winrate = stats["win"] / total
        
        if winrate > 0.65:
            return 1.2
        elif winrate < 0.40:
            return 0.8
        
        return 1.0
    
    def get_hour_multiplier(self) -> float:
        """Retorna multiplicador baseado na hora do dia"""
        hour = str(get_br_now().hour)
        stats = self.data["hour_stats"].get(hour)
        
        if not stats:
            return 1.0
        
        total = stats["win"] + stats["loss"]
        if total < 5:
            return 1.0
        
        winrate = stats["win"] / total
        
        if winrate > 0.65:
            return 1.15
        elif winrate < 0.40:
            return 0.85
        
        return 1.0

# ========================================
# TEMPO
# ========================================
def get_utc_now() -> datetime:
    """Retorna hora UTC atual"""
    return datetime.now(timezone.utc)

def get_br_now() -> datetime:
    """Retorna hora Brasil (UTC-3)"""
    return get_utc_now().astimezone(Config.BR_TIMEZONE)

def floor_minute(dt: datetime) -> datetime:
    """Retorna datetime sem segundos"""
    return dt.replace(second=0, microsecond=0)

def next_minute(dt: datetime) -> datetime:
    """Retorna próximo minuto"""
    return floor_minute(dt) + timedelta(minutes=1)

def fmt_br(dt: datetime) -> str:
    """Formata hora para Brasil (HH:MM)"""
    return dt.astimezone(Config.BR_TIMEZONE).strftime("%H:%M")

# ========================================
# LOG E TELEGRAM
# ========================================
def log(msg: str) -> None:
    """Log com timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)

def send_telegram(msg: str) -> bool:
    """Envia mensagem via Telegram"""
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/sendMessage"
        payload = {"chat_id": Config.CHAT_ID, "text": msg}
        response = requests.post(url, data=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        log(f"❌ Erro envio Telegram: {e}")
        return False

def remove_webhook() -> None:
    """Remove webhook do bot"""
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook"
        requests.get(url, timeout=10)
    except Exception as e:
        log(f"⚠️ Erro ao remover webhook: {e}")

# ========================================
# COMANDOS TELEGRAM
# ========================================
def check_commands(state: BotState) -> None:
    """Verifica comandos do Telegram"""
    try:
        url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates"
        params = {}
        
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
                    f"🎯 Operações ativas: {len(state.active_operations)}"
                )
    
    except Exception as e:
        log(f"❌ Erro ao verificar comandos: {e}")

# ========================================
# KUCOIN API - FOREX
# ========================================
def to_kucoin_symbol(symbol: str) -> str:
    """Converte EURUSD para EUR-USDT (ou formato apropriado)"""
    # KuCoin usa formato: EUR-USDT para pares Forex
    # Se símbolo já tem hífen, retorna como está
    if "-" in symbol:
        return symbol
    
    # Separa em moeda base e quote (ex: EURUSD -> EUR + USD)
    base = symbol[:3]
    quote = symbol[3:]
    
    # Adiciona USDT se necessário (para compatibilidade KuCoin)
    # Alguns pares podem precisar de ajuste
    return f"{base}-{quote}"

def get_candles(symbol: str, limit: int = 120) -> Optional[List[Candle]]:
    """Busca velas de preço Forex"""
    try:
        kucoin_symbol = to_kucoin_symbol(symbol)
        url = "https://api.kucoin.com/api/v1/market/candles"
        params = {"type": "1min", "symbol": kucoin_symbol}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if "data" not in data:
            log(f"⚠️ Resposta inválida para {symbol}")
            return None
        
        candles: List[Candle] = []
        
        for row in reversed(data["data"][:limit]):
            try:
                open_ts = int(float(row[0]))
                open_dt = datetime.fromtimestamp(open_ts, tz=timezone.utc)
                
                candles.append(Candle(
                    time=open_dt,
                    open=float(row[1]),
                    close=float(row[2]),
                    high=float(row[3]),
                    low=float(row[4]),
                    volume=float(row[5]),
                ))
            except (ValueError, IndexError) as e:
                log(f"⚠️ Erro ao parsear vela: {e}")
                continue
        
        return candles if candles else None
    
    except Exception as e:
        log(f"❌ Erro ao buscar candles {symbol}: {e}")
        return None

def find_candle_by_open_time(
    candles: List[Candle],
    open_time: datetime
) -> Optional[Candle]:
    """Encontra vela pela hora de abertura"""
    target = floor_minute(open_time)
    
    for candle in candles:
        if floor_minute(candle.time) == target:
            return candle
    
    return None

# ========================================
# INDICADORES
# ========================================
def calculate_ema(prices: List[float], period: int) -> Optional[float]:
    """Calcula EMA (Exponential Moving Average)"""
    if len(prices) < period:
        return None
    
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    
    for price in prices[period:]:
        ema = (price - ema) * k + ema
    
    return ema

def calculate_rsi(prices: List[float], period: int = 14) -> Optional[float]:
    """Calcula RSI (Relative Strength Index)"""
    if len(prices) < period + 1:
        return None
    
    gains = sum(
        prices[i] - prices[i - 1]
        for i in range(1, period + 1)
        if prices[i] > prices[i - 1]
    )
    
    losses = sum(
        prices[i - 1] - prices[i]
        for i in range(1, period + 1)
        if prices[i] < prices[i - 1]
    )
    
    avg_gain = gains / period
    avg_loss = losses / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

# ========================================
# SELEÇÃO DE ATIVOS
# ========================================
def get_market_symbols() -> List[str]:
    """Retorna símbolos disponíveis no mercado Forex"""
    return Config.ACTIVE_SYMBOLS.copy()

def calculate_asset_quality_score(symbol: str) -> float:
    """Calcula score de qualidade do par Forex"""
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
    
    score = (
        volatility * 50 +
        trend * 120 +
        abs(rsi - 50) * 0.3
    )
    
    return score

def update_active_symbols(learning_mgr: LearningManager, state: BotState) -> None:
    """Atualiza universo de ativos Forex"""
    log("🔄 Atualizando universo de pares Forex...")
    
    market_symbols = get_market_symbols()
    scored_symbols: List[Tuple[str, float]] = []
    
    for symbol in market_symbols:
        try:
            score = calculate_asset_quality_score(symbol)
            scored_symbols.append((symbol, score))
            log(f"  {symbol}: score={score:.3f}")
        except Exception as e:
            log(f"❌ Erro ao calcular score de {symbol}: {e}")
    
    if not scored_symbols:
        Config.ACTIVE_SYMBOLS = ["EURUSD", "GBPUSD"]
        log("⚠️ Fallback para EUR/USD e GBP/USD")
        return
    
    scored_symbols.sort(key=lambda x: x[1], reverse=True)
    top_symbols = [s[0] for s in scored_symbols[:12]]
    
    if len(top_symbols) < 3:
        top_symbols = ["EURUSD", "GBPUSD"]
    
    Config.ACTIVE_SYMBOLS = top_symbols
    state.last_universe_update = get_utc_now()
    
    log(f"✅ Novo universo: {Config.ACTIVE_SYMBOLS}")

# ========================================
# SELEÇÃO DE MELHOR ATIVO
# ========================================
def select_best_asset(
    learning_mgr: LearningManager,
    state: BotState
) -> Optional[Tuple[str, TradeDirection, float]]:
    """Seleciona melhor par Forex para operar"""
    best_symbol: Optional[str] = None
    best_score: float = -1
    best_direction: Optional[TradeDirection] = None
    
    for symbol in Config.ACTIVE_SYMBOLS:
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
        
        if trend_pct < Config.TREND_THRESHOLD:
            continue
        
        # Score base
        score = trend_pct + abs(rsi - 50) * 0.05
        
        # Aplicar multiplicadores
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
        
        # Determinar direção
        if ema_short > ema_long and rsi >= 50:
            direction = TradeDirection.BUY
        elif ema_short < ema_long and rsi <= 50:
            direction = TradeDirection.SELL
        else:
            continue
        
        if score > best_score:
            best_score = score
            best_symbol = symbol
            best_direction = direction
    
    if best_symbol and best_direction:
        return (best_symbol, best_direction, best_score)
    
    return None

# ========================================
# GESTÃO DE SINAIS E OPERAÇÕES
# ========================================
def create_signal(
    setup: PendingSetup,
    state: BotState
) -> None:
    """Cria e envia sinal de entrada"""
    state.pending_setup = setup
    state.last_signal_time = get_utc_now()
    
    direction_emoji = "🟢 COMPRA" if setup.direction == TradeDirection.BUY else "🔴 VENDA"
    
    msg = (
        "⚠️ PREPARAR ENTRADA ⚠️\n\n"
        f"💱 Par: {setup.symbol}\n"
        f"📊 Estratégia: {direction_emoji}\n"
        f"⏰ Entrada prevista: {fmt_br(setup.entry_time)}\n"
        f"📈 Força: {setup.score:.3f}"
    )
    
    send_telegram(msg)
    log(f"📊 SINAL | {setup.symbol} | {setup.direction.value} | {setup.score:.3f}")

def process_pending_setup(state: BotState) -> None:
    """Processa setup pendente quando chega hora da entrada"""
    if state.pending_setup is None:
        return
    
    if get_utc_now() < state.pending_setup.entry_time:
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
    
    msg = (
        "✅ ENTRADA CONFIRMADA ✅\n\n"
        f"💱 Par: {setup.symbol}\n"
        f"📊 Estratégia: {direction_emoji}\n"
        f"⏰ Entrada: {fmt_br(setup.entry_time)}\n\n"
        f"⚠️ Proteção 1: {fmt_br(p1_time)}\n"
        f"⚠️ Proteção 2: {fmt_br(p2_time)}"
    )
    
    send_telegram(msg)

# ========================================
# VERIFICAÇÃO DE RESULTADOS
# ========================================
def check_operation_result(
    operation: ActiveOperation,
    candles: Optional[List[Candle]],
    learning_mgr: LearningManager,
    state: BotState
) -> Optional[ActiveOperation]:
    """
    Verifica resultado de operação.
    Retorna None se operação finalizada, senão retorna operação atualizada.
    """
    
    if candles is None:
        return operation
    
    # Mapear estágio para tempo
    if operation.stage == TradeStage.ENTRY:
        check_time = operation.entry_time
        next_stage = TradeStage.PROTECTION_1
        stage_name = "Entrada"
    elif operation.stage == TradeStage.PROTECTION_1:
        check_time = operation.protection1_time
        next_stage = TradeStage.PROTECTION_2
        stage_name = "Proteção 1"
    else:  # PROTECTION_2
        check_time = operation.protection2_time
        next_stage = None
        stage_name = "Proteção 2"
    
    # Aguardar tempo + margem de segurança
    wait_until = check_time + timedelta(minutes=1, seconds=5)
    if get_utc_now() < wait_until:
        return operation
    
    # Buscar velas
    current_candle = find_candle_by_open_time(candles, check_time)
    previous_candle = find_candle_by_open_time(
        candles,
        check_time - timedelta(minutes=1)
    )
    
    if current_candle is None or previous_candle is None:
        return operation
    
    # Determinar resultado
    is_win = (
        current_candle.close > previous_candle.close
        if operation.direction == TradeDirection.BUY
        else current_candle.close < previous_candle.close
    )
    
    if is_win:
        state.record_win(operation.symbol)
        learning_mgr.record_result(operation.symbol, True)
        
        msg = (
            "🏆 RESULTADO\n\n"
            f"💱 {operation.symbol}\n"
            f"✅ WIN em {stage_name}\n\n"
            f"Wins: {state.wins}\n"
            f"Losses: {state.losses}\n"
            f"Precisão: {state.winrate:.1f}%"
        )
        
        send_telegram(msg)
        log(f"✅ WIN | {operation.symbol} | {stage_name}")
        return None
    
    # Se não ganhou e ainda há proteções, avançar
    if next_stage is not None:
        operation.stage = next_stage
        return operation
    
    # Se chegou na proteção 2 e perdeu
    state.record_loss(operation.symbol)
    learning_mgr.record_result(operation.symbol, False)
    
    msg = (
        "🏆 RESULTADO\n\n"
        f"💱 {operation.symbol}\n"
        f"❌ LOSS após {stage_name}\n\n"
        f"Wins: {state.wins}\n"
        f"Losses: {state.losses}\n"
        f"Precisão: {state.winrate:.1f}%"
    )
    
    send_telegram(msg)
    log(f"❌ LOSS | {operation.symbol} | {stage_name}")
    return None

def check_results(learning_mgr: LearningManager, state: BotState) -> None:
    """Verifica resultados de todas as operações ativas"""
    new_operations: List[ActiveOperation] = []
    
    for operation in state.active_operations:
        candles = get_candles(operation.symbol)
        result = check_operation_result(operation, candles, learning_mgr, state)
        
        if result is not None:
            new_operations.append(result)
    
    state.active_operations = new_operations

# ========================================
# LOOP PRINCIPAL
# ========================================
def main() -> None:
    """Loop principal do bot"""
    
    # Validar configurações
    try:
        Config.validate()
    except ValueError as e:
        log(f"❌ Erro de configuração: {e}")
        return
    
    # Inicializar
    remove_webhook()
    learning_mgr = LearningManager()
    state = BotState()
    
    log("🤖 BOT INICIANDO - FOREX...")
    send_telegram("🤖 BOT INICIADO COM SUCESSO - MODO FOREX 💱")
    
    while True:
        try:
            # Verificar comandos
            check_commands(state)
            
            if not state.is_active:
                time.sleep(5)
                continue
            
            # Atualizar universo de ativos periodicamente
            if (
                state.last_universe_update is None
                or (get_utc_now() - state.last_universe_update).total_seconds()
                > Config.UNIVERSE_REFRESH
            ):
                update_active_symbols(learning_mgr, state)
            
            # Processar setup pendente
            process_pending_setup(state)
            
            # Verificar resultados de operações ativas
            check_results(learning_mgr, state)
            
            # Procurar novo sinal se não há operações ativas
            if (
                state.pending_setup is None
                and not state.active_operations
            ):
                if (
                    state.last_signal_time is None
                    or (get_utc_now() - state.last_signal_time).total_seconds()
                    >= Config.SIGNAL_INTERVAL
                ):
                    result = select_best_asset(learning_mgr, state)
                    
                    if result:
                        symbol, direction, score = result
                        entry_time = next_minute(get_utc_now()) + timedelta(minutes=1)
                        
                        setup = PendingSetup(
                            symbol=symbol,
                            direction=direction,
                            score=score,
                            entry_time=entry_time
                        )
                        
                        create_signal(setup, state)
            
            # Esperar antes de próxima iteração
            time.sleep(10)
        
        except Exception as e:
            log(f"❌ Erro geral: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()

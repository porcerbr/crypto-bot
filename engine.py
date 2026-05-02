"""Motor principal do bot de trading.

Orquestra todos os módulos em um ciclo controlado:
1. Coleta de dados
2. Limpeza e validação
3. Análise de estratégia
4. Filtros de risco
5. Execução (simulada ou real)
6. Persistência de estado
7. Emissão de eventos para dashboard

O engine roda em uma thread separada para não bloquear
o servidor web do dashboard.
"""
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from config import get_settings
from data.collector import DataCollector
from data.cleaner import DataCleaner
from strategy.analyzer import MarketAnalyzer
from strategy.signal_generator import Signal, SignalDirection, SignalGenerator
from risk.filters import RiskFilter
from risk.manager import RiskManager
from execution.dispatcher import ExecutionDispatcher
from storage.database import TradeDatabase
from storage.state_manager import StateManager
from monitoring.health import HealthMonitor
from monitoring.alerts import AlertManager


class BotStatus(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class BotState:
    """Estado completo do bot para serialização e dashboard."""
    status: str = BotStatus.STOPPED.value
    symbol: str = ""
    last_update: Optional[str] = None
    last_signal: Optional[Dict[str, Any]] = None
    open_trades: List[Dict[str, Any]] = field(default_factory=list)
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    total_trades: int = 0
    win_count: int = 0
    loss_count: int = 0
    win_rate: float = 0.0
    active_filters: List[str] = field(default_factory=list)
    recent_errors: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    uptime_seconds: float = 0.0


class TradingEngine:
    """Motor central do sistema de trading.

    Responsabilidades:
    - Gerenciar o ciclo de vida do bot
    - Coordenar módulos sem criar acoplamento direto
    - Manter estado thread-safe
    - Emitir callbacks para o dashboard
    """

    def __init__(self):
        self.settings = get_settings()
        self.status = BotStatus.STOPPED
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._start_time: Optional[datetime] = None

        # Módulos
        self.collector = DataCollector()
        self.cleaner = DataCleaner()
        self.analyzer = MarketAnalyzer()
        self.signal_gen = SignalGenerator()
        self.risk_filter = RiskFilter()
        self.risk_manager = RiskManager()
        self.dispatcher = ExecutionDispatcher()
        self.db = TradeDatabase()
        self.state_mgr = StateManager()
        self.health = HealthMonitor()
        self.alerts = AlertManager()

        # Callbacks para dashboard
        self._callbacks: List[Callable[[BotState], None]] = []
        self._state = BotState()

        # Inicializar estado persistido
        self._load_persisted_state()

    def _load_persisted_state(self):
        """Carrega métricas históricas do banco."""
        try:
            metrics = self.db.get_performance_metrics()
            with self._lock:
                self._state.total_trades = metrics.get("total_trades", 0)
                self._state.win_count = metrics.get("win_count", 0)
                self._state.loss_count = metrics.get("loss_count", 0)
                self._state.daily_pnl = metrics.get("daily_pnl", 0.0)
                self._state.weekly_pnl = metrics.get("weekly_pnl", 0.0)
                self._state.monthly_pnl = metrics.get("monthly_pnl", 0.0)
                if self._state.total_trades > 0:
                    self._state.win_rate = (self._state.win_count / self._state.total_trades) * 100
        except Exception as e:
            self._log_error(f"Erro ao carregar estado persistido: {e}")

    def register_callback(self, callback: Callable[[BotState], None]):
        """Registra callback para atualizações de estado em tempo real."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[BotState], None]):
        """Remove callback registrado."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify(self):
        """Notifica todos os callbacks com o estado atual."""
        state = self.get_state()
        for cb in self._callbacks:
            try:
                cb(state)
            except Exception:
                pass  # Isolar falhas de callbacks

    def get_state(self) -> BotState:
        """Retorna cópia thread-safe do estado atual."""
        with self._lock:
            state = BotState(
                status=self.status.value,
                symbol=self.settings.trading_symbol,
                last_update=self._state.last_update,
                last_signal=self._state.last_signal,
                open_trades=self.db.get_open_trades(),
                daily_pnl=self._state.daily_pnl,
                weekly_pnl=self._state.weekly_pnl,
                monthly_pnl=self._state.monthly_pnl,
                total_trades=self._state.total_trades,
                win_count=self._state.win_count,
                loss_count=self._state.loss_count,
                win_rate=self._state.win_rate,
                active_filters=self._state.active_filters,
                recent_errors=list(self._state.recent_errors)[-10:],
                alerts=list(self._state.alerts)[-5:],
                uptime_seconds=self._get_uptime(),
            )
        return state

    def _get_uptime(self) -> float:
        if self._start_time is None:
            return 0.0
        return (datetime.now(timezone.utc) - self._start_time).total_seconds()

    def _log_error(self, msg: str):
        """Registra erro no estado e no log."""
        import logging
        logging.error(msg)
        with self._lock:
            self._state.recent_errors.append(f"{datetime.now(timezone.utc).isoformat()} - {msg}")
            if len(self._state.recent_errors) > 50:
                self._state.recent_errors.pop(0)

    def _add_alert(self, msg: str):
        with self._lock:
            self._state.alerts.append(f"{datetime.now(timezone.utc).isoformat()} - {msg}")
            if len(self._state.alerts) > 20:
                self._state.alerts.pop(0)

    def start(self):
        """Inicia o motor em thread separada."""
        if self.status == BotStatus.RUNNING:
            return
        self.status = BotStatus.STARTING
        self._stop_event.clear()
        self._start_time = datetime.now(timezone.utc)
        self._thread = threading.Thread(target=self._run, name="TradingEngine", daemon=True)
        self._thread.start()
        self._add_alert("Bot iniciado")

    def stop(self):
        """Sinaliza parada gracefully."""
        if self.status != BotStatus.RUNNING:
            return
        self.status = BotStatus.STOPPED
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10.0)
        self._add_alert("Bot parado")
        self._notify()

    def pause(self):
        """Pausa o ciclo sem matar a thread."""
        if self.status == BotStatus.RUNNING:
            self.status = BotStatus.PAUSED
            self._add_alert("Bot pausado")
            self._notify()

    def resume(self):
        """Retoma de pausa."""
        if self.status == BotStatus.PAUSED:
            self.status = BotStatus.RUNNING
            self._add_alert("Bot retomado")
            self._notify()

    def _run(self):
        """Loop principal do bot."""
        import logging
        logger = logging.getLogger("TradingEngine")
        self.status = BotStatus.RUNNING
        self._notify()

        while not self._stop_event.is_set():
            try:
                if self.status != BotStatus.RUNNING:
                    time.sleep(1)
                    continue

                cycle_start = time.time()
                self._cycle()
                self._state.last_update = datetime.now(timezone.utc).isoformat()

                # Atualizar métricas de saúde
                self.health.record_cycle(time.time() - cycle_start)

                # Notificar dashboard
                self._notify()

                # Aguardar próximo ciclo
                sleep_time = self.settings.collect_interval - (time.time() - cycle_start)
                if sleep_time > 0:
                    self._stop_event.wait(sleep_time)

            except Exception as e:
                self._log_error(f"Erro no loop principal: {e}\n{traceback.format_exc()}")
                self.status = BotStatus.ERROR
                self._notify()
                time.sleep(5)
                # Tentar recuperação
                self.status = BotStatus.RUNNING

    def _cycle(self):
        """Executa um ciclo completo de coleta-análise-execução."""
        import logging
        logger = logging.getLogger("TradingEngine")

        # 1. COLETA
        raw_data = self.collector.fetch(self.settings.trading_symbol, self.settings.lookback_period)
        if raw_data is None or raw_data.empty:
            self._add_alert("Falha na coleta de dados - usando fallback")
            raw_data = self.collector.fallback_data(self.settings.trading_symbol)
            if raw_data is None:
                return

        # 2. LIMPEZA
        clean_data = self.cleaner.process(raw_data)
        if clean_data is None or len(clean_data) < 50:
            self._add_alert("Dados insuficientes após limpeza")
            return

        # 3. ANÁLISE
        market_context = self.analyzer.analyze(clean_data)

        # 4. FILTROS DE RISCO
        filters_active = []
        if not self.risk_filter.is_trading_hours():
            filters_active.append("fora_horario")
        if not self.risk_filter.volatility_ok(clean_data, self.settings.max_volatility_pct):
            filters_active.append("volatilidade_alta")
        if not self.risk_filter.volume_ok(clean_data, self.settings.min_volume_ratio):
            filters_active.append("volume_baixo")
        if self.risk_manager.is_max_exposure_reached():
            filters_active.append("exposicao_maxima")
        if self.risk_manager.is_max_trades_reached():
            filters_active.append("max_operacoes")

        with self._lock:
            self._state.active_filters = filters_active

        # Se houver filtros bloqueantes, não gera sinal
        if filters_active:
            logger.info(f"Ciclo bloqueado por filtros: {filters_active}")
            return

        # 5. GERAÇÃO DE SINAL
        signal = self.signal_gen.generate(clean_data, market_context)
        if signal is None or signal.score < self.settings.min_signal_score:
            return

        # Registrar sinal no estado
        with self._lock:
            self._state.last_signal = {
                "timestamp": signal.timestamp.isoformat(),
                "direction": signal.direction.value,
                "score": signal.score,
                "price": signal.price,
                "reason": signal.reason,
            }

        # 6. EXECUÇÃO
        trade = self.dispatcher.execute(signal, self.settings.is_simulation)
        if trade:
            self.db.save_trade(trade)
            self._update_performance(trade)
            self._add_alert(f"Trade {trade['direction']} @ {trade['entry_price']:.2f} (score: {signal.score})")
            logger.info(f"Trade executado: {trade}")

    def _update_performance(self, trade: Dict[str, Any]):
        """Atualiza métricas de performance após trade."""
        with self._lock:
            self._state.total_trades += 1
            pnl = trade.get("pnl", 0.0)
            if pnl > 0:
                self._state.win_count += 1
                self._state.daily_pnl += pnl
                self._state.weekly_pnl += pnl
                self._state.monthly_pnl += pnl
            else:
                self._state.loss_count += 1
                self._state.daily_pnl += pnl
                self._state.weekly_pnl += pnl
                self._state.monthly_pnl += pnl

            self._state.win_rate = (self._state.win_count / self._state.total_trades) * 100

            # Persistir no banco
            self.db.update_metrics({
                "total_trades": self._state.total_trades,
                "win_count": self._state.win_count,
                "loss_count": self._state.loss_count,
                "daily_pnl": self._state.daily_pnl,
                "weekly_pnl": self._state.weekly_pnl,
                "monthly_pnl": self._state.monthly_pnl,
            })

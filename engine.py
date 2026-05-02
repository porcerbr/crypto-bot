"""
core/engine.py — Motor principal do bot
Orquestra todos os módulos: coleta → análise → risco → execução → storage.
Designed to never crash: toda exceção é capturada, logada e recuperada.
"""

import asyncio
import time
from datetime import datetime
from typing import Optional
from loguru import logger

from core.config import settings
from data.collector import DataCollector
from strategy.analyzer import MarketAnalyzer
from risk.manager import RiskManager
from execution.handler import SignalHandler
from storage.state import StateManager
from storage.history import HistoryManager
from monitoring.health import HealthMonitor
from monitoring.alerts import AlertSystem


class BotEngine:
    """
    Núcleo do sistema. Controla o ciclo de vida completo do bot.
    Responsabilidades:
      - Inicializar todos os subsistemas
      - Executar o loop principal de análise
      - Garantir recuperação de falhas
      - Manter estado consistente
    """

    def __init__(self):
        self._running = False
        self._cycle_count = 0
        self._last_cycle_time: Optional[float] = None
        self._errors_in_row = 0
        self._max_errors_in_row = 5

        # Subsistemas
        self.collector = DataCollector()
        self.analyzer = MarketAnalyzer()
        self.risk_manager = RiskManager()
        self.signal_handler = SignalHandler()
        self.state = StateManager()
        self.history = HistoryManager()
        self.health = HealthMonitor(engine=self)
        self.alerts = AlertSystem()

        # Estado público para a dashboard
        self.status = "initializing"
        self.last_signal = None
        self.current_price = None
        self.last_error = None
        self.start_time = datetime.utcnow()

    # ── Ciclo Principal ───────────────────────────────────────────

    async def run(self):
        """Loop principal. Roda indefinidamente até stop() ser chamado."""
        self._running = True
        self.status = "running"

        logger.info("Engine iniciado — entrando no loop principal")

        # Inicialização dos subsistemas
        await self._initialize_subsystems()

        while self._running:
            cycle_start = time.time()
            self._cycle_count += 1

            logger.info(f"── Ciclo #{self._cycle_count} iniciado ──────────────────────")

            try:
                await self._execute_cycle()
                self._errors_in_row = 0
                self.status = "running"

            except Exception as exc:
                self._errors_in_row += 1
                self.last_error = str(exc)
                logger.error(f"Erro no ciclo #{self._cycle_count}: {exc}", exc_info=True)
                self.health.record_error(str(exc))
                await self.alerts.send(
                    f"⚠️ Erro no ciclo #{self._cycle_count}: {exc}",
                    level="warning",
                )

                if self._errors_in_row >= self._max_errors_in_row:
                    logger.critical(
                        f"{self._errors_in_row} erros consecutivos — bot pausado por 5 minutos"
                    )
                    self.status = "paused_on_error"
                    await asyncio.sleep(300)
                    self._errors_in_row = 0

            elapsed = time.time() - cycle_start
            self._last_cycle_time = elapsed
            wait = max(0, settings.CYCLE_INTERVAL_SECONDS - elapsed)
            logger.info(f"Ciclo concluído em {elapsed:.1f}s — próximo em {wait:.0f}s")
            await asyncio.sleep(wait)

    async def _initialize_subsystems(self):
        """Inicializa banco, estado e health monitor."""
        logger.info("Inicializando subsistemas...")
        self.history.initialize_db()
        self.state.load()
        logger.success("Subsistemas prontos")

    async def _execute_cycle(self):
        """
        Um ciclo completo do bot:
        1. Coletar dados de mercado
        2. Limpar e validar dados
        3. Analisar mercado e calcular indicadores
        4. Aplicar filtros de risco
        5. Gerar sinal (se condições satisfeitas)
        6. Registrar resultado
        """
        logger.debug("Fase 1/6 — Coleta de dados")
        raw_data = await self.collector.fetch(
            symbol=settings.SYMBOL,
            timeframe=settings.TIMEFRAME,
            bars=settings.DATA_LOOKBACK_BARS,
        )

        if raw_data is None or raw_data.empty:
            logger.warning("Dados indisponíveis — ciclo ignorado (fallback ativo)")
            self.health.record_data_miss()
            return

        self.current_price = float(raw_data["close"].iloc[-1])
        logger.debug(f"Preço atual: {self.current_price:.2f} {settings.QUOTE_CURRENCY}")

        logger.debug("Fase 2/6 — Análise de mercado")
        analysis = self.analyzer.analyze(raw_data)
        logger.info(
            f"Análise → Score: {analysis.score:.1f} | "
            f"Direção: {analysis.direction} | "
            f"Regime: {analysis.market_regime}"
        )

        logger.debug("Fase 3/6 — Verificação de risco")
        risk_result = self.risk_manager.evaluate(analysis, self.state)
        if not risk_result.approved:
            logger.info(f"Sinal bloqueado pelo risk manager: {risk_result.reason}")
            self.history.record_blocked(analysis, risk_result)
            return

        logger.debug("Fase 4/6 — Geração de sinal")
        if analysis.score >= settings.MIN_SIGNAL_SCORE and analysis.direction != "neutral":
            signal = self.signal_handler.create_signal(analysis, self.current_price)
            self.last_signal = signal
            self.history.record_signal(signal)
            self.state.add_open_trade(signal)
            self.state.save()

            logger.success(
                f"✅ SINAL GERADO | {signal.direction.upper()} {settings.SYMBOL} "
                f"@ {signal.entry_price:.2f} | SL: {signal.stop_loss:.2f} "
                f"| TP: {signal.take_profit:.2f} | Score: {signal.score:.1f}"
            )
            await self.alerts.send(
                f"🚀 Sinal {signal.direction.upper()} {settings.SYMBOL} "
                f"@ {signal.entry_price:.2f} (score: {signal.score:.1f})",
                level="signal",
            )
        else:
            logger.info(
                f"Score {analysis.score:.1f} < mínimo {settings.MIN_SIGNAL_SCORE} "
                f"— nenhum sinal gerado"
            )

        logger.debug("Fase 5/6 — Atualização de trades abertos")
        self.state.update_open_trades(self.current_price)
        self.state.save()

        logger.debug("Fase 6/6 — Health check")
        self.health.record_cycle(analysis, self.current_price)

    def stop(self):
        logger.info("Stop solicitado — encerrando loop")
        self._running = False
        self.status = "stopped"
        self.state.save()

    # ── Métricas para a Dashboard ─────────────────────────────────

    def get_dashboard_data(self) -> dict:
        """Snapshot completo do estado do bot para a dashboard."""
        perf = self.history.get_performance()
        open_trades = self.state.get_open_trades()
        errors = self.health.get_recent_errors()
        return {
            "status": self.status,
            "symbol": settings.SYMBOL,
            "timeframe": settings.TIMEFRAME,
            "current_price": self.current_price,
            "cycle_count": self._cycle_count,
            "last_cycle_seconds": self._last_cycle_time,
            "uptime_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "start_time": self.start_time.isoformat(),
            "last_signal": self.last_signal.__dict__ if self.last_signal else None,
            "open_trades": [t.__dict__ for t in open_trades],
            "performance": perf,
            "errors": errors,
            "filters_active": self.risk_manager.get_active_filters(),
            "last_error": self.last_error,
            "health": self.health.get_summary(),
        }

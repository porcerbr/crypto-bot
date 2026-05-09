from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from core_engine import MarketEngine
from data_provider import DemoLiveProvider
from risk_risk_manager import RiskManager
from strategies_confluence_strategy import ConfluenceStrategy
from telegram_bot import TelegramNotifier
from utils_config import settings
from utils_logger import setup_logger

logger = setup_logger("api")
engine: MarketEngine | None = None
bg_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine, bg_task
    engine = MarketEngine(
        provider=DemoLiveProvider(),
        strategy=ConfluenceStrategy(),
        risk_manager=RiskManager(),
        notifier=TelegramNotifier(),
    )
    bg_task = asyncio.create_task(engine.run_forever())
    logger.info("Background engine started")
    yield
    if bg_task:
        bg_task.cancel()
        try:
            await bg_task
        except Exception:
            pass


app = FastAPI(title="Forex Signal Bot", version="1.0.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.env, "symbols": settings.symbols_list}


@app.get("/signals")
async def signals():
    if engine is None:
        return JSONResponse({"signals": []})
    data = []
    for s in engine.latest_signals:
        data.append({
            "symbol": s.symbol,
            "side": s.side.value,
            "timeframe": s.timeframe,
            "entry": s.entry,
            "stop_loss": s.stop_loss,
            "take_profit": s.take_profit,
            "rr": s.rr,
            "score": s.score,
            "confidence": s.confidence,
            "probability": s.probability,
            "reason": s.reason,
            "created_at": s.created_at.isoformat(),
            "position_size": s.position_size,
        })
    return {"signals": data}

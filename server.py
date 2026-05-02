"""
dashboard/server.py — Servidor FastAPI da dashboard
Expõe API JSON para o frontend e serve o HTML estático.
"""

import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from core.config import settings

app = FastAPI(title="TradingBot Dashboard", version="1.0.0", docs_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

_engine = None


@app.get("/api/status")
async def api_status():
    if _engine is None:
        return JSONResponse({"status": "initializing"})
    try:
        data = _engine.get_dashboard_data()
        return JSONResponse(data)
    except Exception as exc:
        logger.error(f"Dashboard API error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/health")
async def api_health():
    return JSONResponse({"ok": True, "status": getattr(_engine, "status", "unknown")})


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


def start_dashboard(engine):
    global _engine
    _engine = engine
    logger.info(f"Iniciando dashboard em {settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}")
    uvicorn.run(
        app,
        host=settings.DASHBOARD_HOST,
        port=settings.DASHBOARD_PORT,
        log_level="warning",
    )

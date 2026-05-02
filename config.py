from dataclasses import dataclass, field
from typing import List
import os

@dataclass
class BotConfig:
    bot_name: str = "ProfessionalSignalBot"
    mode: str = "signals"  # signals | paper | execution

    symbols: List[str] = field(default_factory=lambda: ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD"])
    timeframe: str = "1h"
    lookback_bars: int = 250

    risk_per_trade_pct: float = 0.5
    max_open_trades: int = 3
    max_daily_loss_pct: float = 2.0
    min_rr: float = 1.5
    max_rr: float = 3.0
    default_rr: float = 2.0
    cooldown_minutes_after_loss: int = 30

    min_score_to_signal: int = 8
    use_trend_filter: bool = True
    use_volatility_filter: bool = True
    use_spread_filter: bool = True
    use_session_filter: bool = True
    use_news_filter: bool = True

    poll_seconds: int = 60
    sl_buffer_pips: float = 2.0
    sl_atr_multiplier: float = 1.2

    london_start_utc: int = 7
    london_end_utc: int = 16
    new_york_start_utc: int = 12
    new_york_end_utc: int = 21

    state_path: str = "state.json"
    logs_dir: str = "logs"

    host: str = "0.0.0.0"
    port: int = int(os.getenv("PORT", "8080"))

    api_key: str = os.getenv("TWELVEDATA_API_KEY", "")
    base_url: str = os.getenv("TWELVEDATA_BASE_URL", "https://api.twelvedata.com")

from __future__ import annotations
from config import BotConfig
from bot import TradingBot
from app import create_app

def main() -> None:
    config = BotConfig()
    bot = TradingBot(config)
    app = create_app(bot)
    bot.start()
    app.run(host=config.host, port=config.port, debug=False, use_reloader=False)

if __name__ == "__main__":
    main()

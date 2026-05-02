from __future__ import annotations
from config import BotConfig
from data_provider import TwelveDataProvider
from backtest import Backtester

def main():
    config = BotConfig()
    provider = TwelveDataProvider(config.api_key, config.base_url)
    candles = provider.get_candles("EUR/USD", "1h", 1000)
    result = Backtester(config).run("EUR/USD", candles)
    print(result)

if __name__ == "__main__":
    main()

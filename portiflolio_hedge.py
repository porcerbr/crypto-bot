HEDGE_PAIRS = {
    "EURUSD": ["USDCHF", "USDCAD"],
    "GBPUSD": ["USDJPY"],
    "XAUUSD": ["XAGUSD", "USDCAD"],
    "BTCUSD": ["ETHUSD"],
}

def calc_hedge_score(active_trades):
    if len(active_trades) < 2:
        return None
    buy_syms = [t["symbol"] for t in active_trades if t["dir"] == "BUY"]
    sell_syms = [t["symbol"] for t in active_trades if t["dir"] == "SELL"]
    active_syms = [t["symbol"] for t in active_trades]

    if len(buy_syms) >= 2:
        for sym in buy_syms:
            if sym in HEDGE_PAIRS:
                for hedge_sym in HEDGE_PAIRS[sym]:
                    if hedge_sym not in active_syms:
                        return (hedge_sym, "SELL", sym)
    if len(sell_syms) >= 2:
        for sym in sell_syms:
            if sym in HEDGE_PAIRS:
                for hedge_sym in HEDGE_PAIRS[sym]:
                    if hedge_sym not in active_syms:
                        return (hedge_sym, "BUY", sym)
    return None

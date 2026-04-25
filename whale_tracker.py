import time, requests
from config import Config
from utils import log

_cached_whales = []
_cache_ts = 0

def get_whale_alerts(symbols=None):
    global _cached_whales, _cache_ts
    now = time.time()
    if now - _cache_ts < 300:
        return [w for w in _cached_whales if symbols is None or w["symbol"] in symbols]

    if not Config.WHALE_ALERT_API_KEY:
        return []

    try:
        url = f"https://api.whale-alert.io/v1/transactions?api_key={Config.WHALE_ALERT_API_KEY}&min_value=500000&limit=50"
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            log(f"[WHALE] Erro API: {resp.status_code}")
            return []
        data = resp.json()
        whales = []
        for tx in data.get("transactions", []):
            symbol = tx.get("symbol", "")
            if not symbol:
                continue
            whales.append({
                "symbol": symbol,
                "amount_usd": tx.get("amount_usd", 0),
                "from_owner": tx.get("from", {}).get("owner_type", "unknown"),
                "to_owner": tx.get("to", {}).get("owner_type", "unknown"),
            })
        _cached_whales = whales
        _cache_ts = now
        log(f"[WHALE] {len(whales)} alertas carregados")
        return [w for w in whales if symbols is None or w["symbol"] in symbols]
    except Exception as e:
        log(f"[WHALE] Erro: {e}")
        return []

def whale_signal_for(symbol):
    alerts = get_whale_alerts([symbol])
    if not alerts:
        return 0, []
    score = 0
    reasons = []
    for a in alerts:
        if "exchange" in a["to_owner"].lower():
            score -= 1
            reasons.append(f"${a['amount_usd']:,.0f} → exchange")
        elif "exchange" in a["from_owner"].lower():
            score += 1
            reasons.append(f"${a['amount_usd']:,.0f} ← exchange")
    if reasons:
        score = max(-1, min(1, score / len(reasons)))
    return score, reasons[:3]

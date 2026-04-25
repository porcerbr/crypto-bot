import requests
from config import Config
from utils import log

def analyze_sentiment(texts):
    if not Config.HF_API_TOKEN or not texts:
        return 0, []
    try:
        headers = {"Authorization": f"Bearer {Config.HF_API_TOKEN}"}
        payload = {"inputs": texts}
        resp = requests.post(
            "https://api-inference.huggingface.co/models/ProsusAI/finbert",
            headers=headers, json=payload, timeout=10
        )
        if resp.status_code != 200:
            log(f"[SENTIMENT] Erro API: {resp.status_code}")
            return 0, []
        results = resp.json()
        scores = []
        reasons = []
        for i, res in enumerate(results):
            if not res:
                continue
            pos = next((d["score"] for d in res if d["label"] == "positive"), 0)
            neg = next((d["score"] for d in res if d["label"] == "negative"), 0)
            s = pos - neg
            scores.append(s)
            if abs(s) > 0.5 and i < len(texts):
                reasons.append((texts[i][:100], round(s, 2)))
        avg = sum(scores) / len(scores) if scores else 0
        return avg, reasons[:3]
    except Exception as e:
        log(f"[SENTIMENT] Erro: {e}")
        return 0, []

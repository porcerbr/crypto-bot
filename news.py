# news.py
import requests, xml.etree.ElementTree as ET, time
from config import Config
from utils import log

RSS_FEEDS = [
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Yahoo Finance", "https://finance.yahoo.com/rss/topfinstories"),
]

def _parse_rss(url, src, mx=3):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        out = []
        for item in items[:mx]:
            title = (item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or "  ").strip()
            link  = (item.findtext("link")  or item.findtext("{http://www.w3.org/2005/Atom}link")  or "  ").strip()
            if title and link: out.append({"title": title, "url": link, "source": src})
        return out
    except: return []

def get_news(mx=15):
    arts = []
    for name, url in RSS_FEEDS:
        if len(arts) >= mx: break
        try: arts.extend(_parse_rss(url, name, 4))
        except Exception as e: log(f"[RSS] {name}: {e}")
    return arts[:mx]

def get_fear_greed():
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1", timeout=6).json()["data"][0]
        return {"value": d["value"], "label": d["value_classification"]}
    except: return {"value": "N/D", "label": " "}

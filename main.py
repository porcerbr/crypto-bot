# main.py
import time, threading, requests, os
from flask import Response
from config import Config
from utils import log
from db import load_state, save_state
from bot import TradingBot
from signals import scan
from api import create_api

def bot_loop(bot):
    while True:
        if not bot.is_paused():
            try:
                scan(bot)
                bot.monitor_trades()
            except Exception as e:
                log(f"Erro no loop: {e}")
        # Processa comandos do Telegram (simplificado)
        try:
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_id+1}&timeout=5"
            resp = requests.get(url, timeout=10).json()
            if "result" in resp:
                for u in resp["result"]:
                    if "message" in u and "text" in u["message"]:
                        txt = u["message"]["text"].strip()
                        if txt.startswith("/executar_"):
                            parts = txt.split("_")
                            pid = int(parts[1])
                            amount = float(parts[2])
                            bot.execute_pending(pid, amount)
                    bot.last_id = u["update_id"]
        except Exception:
            pass
        time.sleep(Config.SCAN_INTERVAL)

def main():
    log("Iniciando Sniper Bot v2 (Yahoo Finance)")
    bot = TradingBot()
    load_state(bot)
    threading.Thread(target=bot_loop, args=(bot,), daemon=True).start()
    app = create_api(bot)
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()

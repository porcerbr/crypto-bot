
# 3. main.py corrigido - codigo PURO do bot, sem nada de geracao de arquivo
main_content = '''# main.py
import threading, requests, time
from config import Config
from utils import log, fmt, account_snapshot
from db import init_db, load_state
from bot_core import TradingBot

def bot_loop(bot):
    bot.build_menu()
    if bot._restore_msg:
        bot.send(bot._restore_msg)
        bot._restore_msg = None
    try:
        bot.send_news()
    except:
        pass
    while True:
        try:
            url = f"https://api.telegram.org/bot{Config.BOT_TOKEN}/getUpdates?offset={bot.last_id+1}&timeout=5"
            r = requests.get(url, timeout=12).json()
            if "result" in r:
                for u in r["result"]:
                    bot.last_id = u["update_id"]
                    if "message" in u:
                        txt = u["message"].get("text", "").strip().lower()
                        if bot.awaiting_custom_amount and txt not in ("/cancelar", "cancelar"):
                            try:
                                amount = float(txt.replace(",", "."))
                                if amount <= 0:
                                    raise ValueError
                                pid = bot.awaiting_custom_amount
                                bot.awaiting_custom_amount = None
                                bot.execute_pending_with_amount(pid, amount, source="telegram")
                            except:
                                bot.send("Envie apenas um valor numerico valido, por exemplo: <code>500</code>")
                        elif txt in ("/noticias", "/news"):
                            bot.send_news()
                        elif txt == "/status":
                            bot.send_status()
                        elif txt in ("/placar", "/score"):
                            bot.send_placar()
                        elif txt.startswith("/setsaldo"):
                            try:
                                parts = txt.split()
                                if len(parts) < 2:
                                    raise ValueError
                                val = float(parts[1].replace(",", "."))
                                if bot.set_balance(val):
                                    bot.send(f"Saldo ajustado para <code>{fmt(bot.balance)}</code>")
                                else:
                                    bot.send("Saldo invalido. Use: <code>/setsaldo 500</code>")
                            except:
                                bot.send("Use: <code>/setsaldo 500</code>")
                        elif txt in ("/saldo", "/account"):
                            snap = account_snapshot(bot)
                            bot.send(f"Saldo: <code>{fmt(bot.balance)}</code> | Equity: <code>{fmt(snap['equity'])}</code> | Alav.: <code>{bot.leverage}x</code>")
                        elif txt in ("/menu", "/start"):
                            bot.build_menu()
                        elif txt == "/resetpausa":
                            bot.reset_pause()
                    if "callback_query" in u:
                        cb = u["callback_query"]["data"]
                        cid = u["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/answerCallbackQuery", json={"callback_query_id": cid}, timeout=5)
                        if cb.startswith("set_tf"):
                            bot.set_timeframe(cb.replace("set_tf_", ""))
                        elif cb.startswith("set"):
                            bot.set_mode(cb.replace("set_", ""))
                        elif cb == "tf_menu":
                            bot.build_tf_menu()
                        elif cb == "main_menu":
                            bot.build_menu()
                        elif cb == "news":
                            bot.send_news()
                        elif cb == "status":
                            bot.send_status()
                        elif cb == "placar":
                            bot.send_placar()
                        elif cb.startswith("amt_"):
                            try:
                                parte = cb.split("_", 2)
                                pid = int(parte[2])
                                amt = float(parte[1])
                                bot.execute_pending_with_amount(pid, amt, source="telegram")
                            except:
                                pass
                        elif cb.startswith("amtcustom_"):
                            try:
                                bot.request_custom_amount(int(cb.split("_")[1]))
                            except:
                                pass
                        elif cb.startswith("confirm_"):
                            try:
                                bot.confirm_pending(int(cb.split("_")[1]))
                            except:
                                pass
                        elif cb.startswith("reject"):
                            try:
                                bot.reject_pending(int(cb.split("_")[1]))
                            except:
                                pass
            bot.update_trends_cache()
            bot.maybe_send_news()
            from signals import scan, scan_reversal_forex
            scan(bot)
            scan_reversal_forex(bot)
            bot.monitor_trades()
            time.sleep(Config.SCAN_INTERVAL)
        except Exception as e:
            log(f"Erro loop: {e}")
            time.sleep(10)

def main():
    log("Tickmill Sniper Bot v11.0 MODULAR - MT5 | Raw ECN")
    init_db()
    try:
        requests.get(f"https://api.telegram.org/bot{Config.BOT_TOKEN}/deleteWebhook", timeout=8)
    except:
        pass
    bot = TradingBot()
    load_state(bot)
    t = threading.Thread(target=bot_loop, args=(bot,), daemon=True)
    t.start()
    from api import run_api
    run_api(bot)

if __name__ == "__main__":
    main()
'''

with open("/mnt/agents/output/main.py", "w", encoding="utf-8") as f:
    f.write(main_content)

print(f"main.py: {len(main_content)} chars")
print("\n=== TODOS OS ARQUIVOS GERADOS ===")
print("1. dashboard.html - HTML puro (nao e Python)")
print("2. api.py - Le dashboard.html de arquivo")
print("3. main.py - Entry point do bot (sem codigo de geracao)")

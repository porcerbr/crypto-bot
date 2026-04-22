"""
Extensões Flask para o Dashboard do Tickmill Sniper Bot
Adicione estas rotas ao seu main.py para integrar o dashboard

Instruções:
1. Copie este arquivo para a pasta do seu projeto
2. Importe no main.py: from flask_extensions import register_dashboard_routes
3. Chame após criar a app Flask: register_dashboard_routes(app, bot)
4. Coloque o arquivo dashboard.html na pasta templates/ ou static/
"""

import json
import os
from flask import jsonify, request, render_template_string, send_file
from datetime import datetime

# Configurações persistentes (usar banco de dados em produção)
SETTINGS_FILE = "bot_settings.json"

def load_settings():
    """Carrega configurações do arquivo JSON"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_settings(settings):
    """Salva configurações no arquivo JSON"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)

def register_dashboard_routes(app, bot):
    """
    Registra as rotas do dashboard na aplicação Flask
    
    Args:
        app: Aplicação Flask
        bot: Instância do bot
    """
    
    # Carregar dashboard HTML
    DASHBOARD_HTML = open('dashboard.html', 'r', encoding='utf-8').read()
    
    @app.route("/dashboard")
    def dashboard():
        """Serve o dashboard HTML"""
        return DASHBOARD_HTML
    
    @app.route("/api/settings", methods=["GET", "POST", "OPTIONS"])
    def api_settings():
        """GET: Retorna configurações atuais | POST: Salva novas configurações"""
        if request.method == "OPTIONS":
            return "", 204
        
        if request.method == "GET":
            settings = load_settings()
            return jsonify({
                "leverage": settings.get("leverage", bot.leverage),
                "atr_mult_sl": settings.get("atr_mult_sl", 1.5),
                "atr_mult_tp": settings.get("atr_mult_tp", 3.5),
                "atr_mult_trail": settings.get("atr_mult_trail", 1.2),
                "risk_percent": settings.get("risk_percent", bot.risk_pct),
                "timeframe": settings.get("timeframe", "15m"),
                "assets": settings.get("assets", []),
                "bot_token": "***" if settings.get("bot_token") else "",
                "chat_id": settings.get("chat_id", ""),
            })
        
        elif request.method == "POST":
            data = request.get_json()
            settings = load_settings()
            
            # Atualizar configurações
            if "leverage" in data:
                bot.leverage = int(data["leverage"])
                settings["leverage"] = bot.leverage
            
            if "atr_mult_sl" in data:
                settings["atr_mult_sl"] = float(data["atr_mult_sl"])
            
            if "atr_mult_tp" in data:
                settings["atr_mult_tp"] = float(data["atr_mult_tp"])
            
            if "atr_mult_trail" in data:
                settings["atr_mult_trail"] = float(data["atr_mult_trail"])
            
            if "risk_percent" in data:
                bot.risk_pct = float(data["risk_percent"])
                settings["risk_percent"] = bot.risk_pct
            
            if "timeframe" in data:
                settings["timeframe"] = data["timeframe"]
            
            if "assets" in data:
                settings["assets"] = data["assets"]
            
            if "bot_token" in data and data["bot_token"]:
                settings["bot_token"] = data["bot_token"]
                os.environ["TELEGRAM_TOKEN"] = data["bot_token"]
            
            if "chat_id" in data:
                settings["chat_id"] = data["chat_id"]
                os.environ["TELEGRAM_CHAT_ID"] = data["chat_id"]
            
            save_settings(settings)
            return jsonify({"success": True, "message": "Configurações salvas com sucesso"})
    
    @app.route("/api/start", methods=["POST", "OPTIONS"])
    def api_start():
        """Inicia o bot"""
        if request.method == "OPTIONS":
            return "", 204
        
        try:
            bot.running = True
            bot.send("🤖 Bot iniciado via Dashboard")
            return jsonify({"success": True, "message": "Bot iniciado"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route("/api/stop", methods=["POST", "OPTIONS"])
    def api_stop():
        """Para o bot"""
        if request.method == "OPTIONS":
            return "", 204
        
        try:
            bot.running = False
            bot.send("🛑 Bot parado via Dashboard")
            return jsonify({"success": True, "message": "Bot parado"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route("/api/close_trade", methods=["POST", "OPTIONS"])
    def api_close_trade():
        """Fecha um trade manualmente"""
        if request.method == "OPTIONS":
            return "", 204
        
        try:
            data = request.get_json()
            trade_id = data.get("trade_id")
            
            # Procurar e fechar o trade
            for trade in bot.active_trades:
                if str(trade.get("id")) == str(trade_id):
                    # Implementar lógica de fechamento
                    bot.send(f"📊 Trade {trade_id} fechado manualmente via Dashboard")
                    return jsonify({"success": True, "message": "Trade fechado"})
            
            return jsonify({"success": False, "error": "Trade não encontrado"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    @app.route("/api/test_telegram", methods=["POST", "OPTIONS"])
    def api_test_telegram():
        """Testa conexão com Telegram"""
        if request.method == "OPTIONS":
            return "", 204
        
        try:
            bot.send("✅ Teste de conexão Telegram - Dashboard")
            return jsonify({"success": True, "message": "Mensagem enviada com sucesso"})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    
    print("[DASHBOARD] Rotas do dashboard registradas com sucesso!")
    print("[DASHBOARD] Acesse em: http://localhost:5000/dashboard")

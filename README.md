# TradingBot Professional

Sistema de trading automatizado com arquitetura modular, dashboard web em tempo real, controle de risco multicamada e persistência completa de dados.

---

## Estrutura de Pastas

```
trading-bot/
├── main.py                    # Ponto de entrada — inicia tudo
├── requirements.txt           # Dependências Python
├── .env.example               # Template de configuração
│
├── core/
│   ├── config.py              # Todas as configs via .env
│   └── engine.py              # Loop principal do bot
│
├── data/
│   └── collector.py           # Coleta OHLCV com retry e cache
│
├── strategy/
│   ├── indicators.py          # RSI, MACD, EMA, BB, ADX, ATR, Stoch
│   └── analyzer.py            # Análise multi-indicador com score 0-100
│
├── risk/
│   └── manager.py             # 7 filtros de segurança independentes
│
├── execution/
│   └── handler.py             # Criação de sinais com SL/TP automáticos
│
├── storage/
│   ├── state.py               # Estado persistente em JSON
│   └── history.py             # Histórico completo em SQLite
│
├── monitoring/
│   ├── health.py              # Métricas de saúde do sistema
│   └── alerts.py              # Alertas (Telegram + extensível)
│
├── dashboard/
│   ├── server.py              # FastAPI — API JSON + serve HTML
│   └── static/index.html      # Dashboard profissional
│
├── data/                      # Criado automaticamente
│   ├── bot.db                 # SQLite com histórico
│   └── state.json             # Estado atual do bot
│
└── logs/                      # Criado automaticamente
    ├── bot_YYYY-MM-DD.log     # Log técnico diário (comprimido aos 30 dias)
    └── errors_YYYY-MM-DD.log  # Somente erros
```

---

## Instalação

### Requisitos
- Python 3.11+
- pip

### Passos

```bash
# 1. Clone ou extraia o projeto
cd trading-bot

# 2. Crie ambiente virtual (recomendado)
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
.venv\Scripts\activate          # Windows

# 3. Instale as dependências
pip install -r requirements.txt

# 4. Configure o ambiente
cp .env.example .env
# Edite .env conforme necessário

# 5. Execute
python main.py
```

A dashboard ficará disponível em **http://localhost:8080**

---

## Como Funciona — Módulo a Módulo

### `core/engine.py` — Motor Principal
Orquestra todo o fluxo em um loop assíncrono:
1. Coleta dados → 2. Analisa → 3. Verifica risco → 4. Gera sinal → 5. Registra → 6. Aguarda próximo ciclo

Recupera-se automaticamente de erros. Após 5 erros consecutivos, pausa 5 minutos.

### `core/config.py` — Configuração
Centraliza todas as configurações via variáveis de ambiente. Nunca use valores hardcoded no código.

### `data/collector.py` — Coleta de Dados
- Retry automático com backoff exponencial
- Cache local como fallback quando API falha
- Suporte a yfinance (gratuito) e Binance
- Timeout configurável por chamada

### `strategy/indicators.py` — Indicadores
Implementações puras em pandas/numpy:
RSI, MACD, EMA, SMA, Bollinger Bands, ATR, Stochastic, ADX, Volume SMA

### `strategy/analyzer.py` — Análise e Score
Sistema de pontuação ponderada (0-100):
- RSI: 20 pts
- MACD: 25 pts
- EMA Cross: 20 pts
- Bollinger Bands: 15 pts
- Volume: 10 pts
- ADX: 10 pts

Detecta regime de mercado: trending_up, trending_down, ranging, volatile.

### `risk/manager.py` — Gerenciamento de Risco
7 filtros sequenciais, qualquer um pode bloquear a entrada:
1. Máximo de trades simultâneos
2. Limite diário de operações
3. Drawdown máximo
4. Volume mínimo
5. Regime de mercado (bloqueia em volatilidade excessiva)
6. ADX mínimo (exige direção clara)
7. Score mínimo para entrada

### `execution/handler.py` — Geração de Sinal
Cria objeto `Signal` com SL e TP calculados automaticamente com base nas configurações de risco. Atualiza status (hit_tp/hit_sl) em cada ciclo.

### `storage/state.py` — Estado Persistente
Salva em JSON após cada ciclo: trades abertos, capital atual, peak capital, contadores diários. Restaura estado após reinicialização.

### `storage/history.py` — Histórico SQLite
Persiste todos os sinais, bloqueios e ciclos. Calcula métricas de desempenho (win rate, PnL por período).

### `monitoring/health.py` — Saúde do Sistema
Rastreia: erros, data misses, tempos de ciclo, disponibilidade de dados.

### `monitoring/alerts.py` — Alertas
Suporte nativo a Telegram. Para ativar: configure `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID` no `.env`.

### `dashboard/` — Interface Web
FastAPI serve o HTML em `/` e a API JSON em `/api/status`. A dashboard atualiza automaticamente a cada 5 segundos.

---

## Dashboard — O Que Mostra

| Seção | Conteúdo |
|-------|----------|
| Header | Status do bot, uptime em tempo real |
| KPIs | Ativo, ciclos, win rate, trades abertos |
| Último Sinal | Direção, entrada, SL, TP, R:R, status |
| Score | Pontuação 0-100 com barra visual e razões |
| Indicadores | RSI, ADX, MACD, EMA, Volume, ATR, BB |
| Performance | PnL e trades por dia/semana/mês |
| Histórico | Tabela dos últimos 15 sinais |
| Filtros | Quais filtros de risco estão bloqueando |
| Erros | Log dos últimos erros com timestamp |
| Saúde | Data misses, ciclo médio, última atualização |

---

## Configuração Avançada

### Trocar símbolo
```env
SYMBOL=ETH-USD
TIMEFRAME=4h
```

### Modo mais conservador
```env
MIN_SIGNAL_SCORE=75.0
MAX_OPEN_TRADES=1
STOP_LOSS_PCT=1.5
TAKE_PROFIT_PCT=3.0
```

### Ciclos mais rápidos (15m)
```env
TIMEFRAME=15m
CYCLE_INTERVAL_SECONDS=60
```

### Habilitar Telegram
```env
TELEGRAM_TOKEN=seu_token_aqui
TELEGRAM_CHAT_ID=seu_chat_id
ALERT_ON_SIGNAL=true
```

---

## Adicionando Novos Provedores de Dados

Em `data/collector.py`, adicione um novo método `_fetch_seuprovedor()` e registre-o no `_fetch_from()`:

```python
elif provider == "seuprovedor":
    return await self._fetch_seuprovedor(symbol, timeframe, bars)
```

---

## Implantação em Produção

### VPS com systemd

```ini
# /etc/systemd/system/tradingbot.service
[Unit]
Description=TradingBot Professional
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/trading-bot
ExecStart=/home/ubuntu/trading-bot/.venv/bin/python main.py
Restart=always
RestartSec=10
Environment=ENV=production

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable tradingbot
sudo systemctl start tradingbot
sudo journalctl -u tradingbot -f
```

### Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["python", "main.py"]
```

```bash
docker build -t tradingbot .
docker run -d -p 8080:8080 --env-file .env tradingbot
```

---

## ⚠️ Aviso Legal

Este sistema é destinado a fins **educacionais e de pesquisa**. Os sinais gerados são informativos e não constituem recomendação de investimento. Sempre consulte um profissional financeiro antes de operar com capital real.

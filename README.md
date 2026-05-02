# Trading Bot Pro

Sistema profissional de trading automatizado com arquitetura modular, dashboard em tempo real e foco em estabilidade.

## Arquitetura

```
trading_bot_pro/
├── config/          # Configurações centralizadas (Pydantic + .env)
├── core/            # Motor principal e orquestração
├── data/            # Coleta e limpeza de dados
├── strategy/        # Análise técnica e geração de sinais
├── risk/            # Filtros e gerenciamento de risco
├── execution/       # Execução de ordens (simulada/live)
├── storage/         # Persistência SQLite + estado JSON
├── dashboard/       # Interface web Flask + SocketIO
├── monitoring/      # Health checks e alertas
├── logs/            # Logs rotativos
└── data_storage/    # Banco de dados e estado
```

## Decisões Técnicas

- **SQLite**: Escolhido por ser serverless e ideal para Railway (single instance). Para multi-instance futuro, basta trocar o `storage/database.py` para PostgreSQL sem afetar o restante.
- **Pydantic Settings**: Validação de configuração em tempo de inicialização. Erros de .env são detectados antes do bot rodar.
- **Threading**: Engine roda em thread separada do servidor web, evitando que falhas de rede bloqueiem o dashboard.
- **Fallback de dados**: Se Yahoo Finance falhar, o bot usa cache local. Se o cache estiver vazio, o ciclo é pulado gracefully.
- **RotatingFileHandler**: Logs não crescem infinitamente, essencial para containers.

## Instalação Local

```bash
# 1. Clone/Extraia o projeto
cd trading_bot_pro

# 2. Ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate  # Windows

# 3. Dependências
pip install -r requirements.txt

# 4. Configuração
cp .env.example .env
# Edite .env conforme necessidade

# 5. Execução
python main.py
```

Acesse: http://localhost:5000

## Deploy no Railway

### Opção 1: Git + Railway CLI
```bash
# Inicialize git no projeto
git init
git add .
git commit -m "Initial commit"

# Railway
railway login
railway init
railway up
```

### Opção 2: Docker (recomendado)
Railway detecta o Dockerfile automaticamente:
```bash
railway login
railway init
railway up
```

### Variáveis de Ambiente no Railway
No painel do Railway, adicione as variáveis do `.env`:
- `OPERATION_MODE=SIMULATION`
- `TRADING_SYMBOL=BTC-USD`
- `SECRET_KEY=<gerar aleatório forte>`

### Healthcheck
O Railway usa o endpoint `/api/health` para verificar saúde do container.

## Configuração (.env)

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `OPERATION_MODE` | SIMULATION ou LIVE | SIMULATION |
| `TRADING_SYMBOL` | Ativo (Yahoo Finance) | BTC-USD |
| `COLLECT_INTERVAL` | Segundos entre ciclos | 60 |
| `TIMEFRAME` | Timeframe análise | 5m |
| `MAX_RISK_PER_TRADE` | % risco por trade | 2.0 |
| `MAX_EXPOSURE` | % exposição máxima | 10.0 |
| `MAX_OPEN_TRADES` | Máximo simultâneo | 3 |
| `MIN_SIGNAL_SCORE` | Score mínimo (0-100) | 65 |
| `DASHBOARD_PORT` | Porta web | 5000 |

## Funcionamento dos Módulos

### Core (Engine)
Orquestra o ciclo: coleta → limpeza → análise → filtros → sinal → execução → persistência. Roda em thread daemon com graceful shutdown.

### Data
- **Collector**: Busca dados Yahoo Finance com retry e backoff exponencial. Timeout de 15s.
- **Cleaner**: Remove outliers (>20% variação), valida OHLC, preenche gaps.

### Strategy
- **Analyzer**: Calcula RSI, EMA(9/21), Bollinger, ATR, Volume ratio.
- **SignalGenerator**: Score ponderado (Tendência 30%, RSI 25%, Bollinger 20%, Volume 15%, Volatilidade 10%). Só emite sinal se score >= 65.

### Risk
- **Filters**: Horário, volatilidade, volume.
- **Manager**: Exposição máxima, limite de trades abertos, cálculo de position size.

### Execution
Modo SIMULATION: simula preenchimento e P&L aleatório realista. Modo LIVE: estrutura pronta para integração com API de corretora.

### Storage
- **TradeDatabase**: SQLite thread-safe com trades e métricas.
- **StateManager**: JSON para estado runtime (recuperação de crash).

### Dashboard
Flask + SocketIO. Atualizações em tempo real via WebSocket. Design dark mode, responsivo.

### Monitoring
- **HealthMonitor**: Estatísticas de tempo de ciclo.
- **AlertManager**: Sistema extensível para notificações externas.

## API Endpoints

| Endpoint | Método | Descrição |
|----------|--------|-----------|
| `/` | GET | Dashboard |
| `/api/health` | GET | Healthcheck (Railway) |
| `/api/state` | GET | Estado completo JSON |
| `/api/trades` | GET | Trades recentes |
| `/api/start` | GET | Iniciar bot |
| `/api/stop` | GET | Parar bot |
| `/api/pause` | GET | Pausar bot |
| `/api/resume` | GET | Retomar bot |

## Evoluções Futuras

- [ ] Integração com corretora real (Binance, Bybit, etc.)
- [ ] Múltiplos ativos simultâneos
- [ ] Backtesting engine
- [ ] Notificações Telegram/Discord
- [ ] Banco PostgreSQL para multi-instance
- [ ] Machine Learning para scoring

## Licença

Uso privado. Desenvolvido para operação própria.

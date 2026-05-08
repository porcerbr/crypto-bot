# 🎯 Sniper Bot — FX & Gold Signal Engine

> **Este bot é SINALIZADOR apenas.** Não executa ordens em corretora real.  
> Todos os cálculos de saldo / P&L são simulados para fins de estatística e treinamento.

---

## Índice

- [Visão Geral](#visão-geral)
- [Arquitetura](#arquitetura)
- [Instalação](#instalação)
- [Variáveis de Ambiente](#variáveis-de-ambiente)
- [Execução](#execução)
- [Risco e Proteções](#risco-e-proteções)
- [Backtesting](#backtesting)
- [Dashboard](#dashboard)
- [Testes](#testes)
- [Deploy Railway](#deploy-railway)

---

## Visão Geral

O Sniper Bot é um sinalizador inteligente de Forex e Ouro que combina:

- **Análise técnica multi-timeframe** (EMA, RSI, MACD, Bollinger, ATR, Stoch)
- **Filtro de notícias** de alto impacto (FED, NFP, CPI, etc.)
- **Filtro COT** (posicionamento institucional CFTC)
- **Validação por IA** (Google Gemini) com score de confiança 0–10
- **Gestão de risco** com limites diários/semanais e circuit breakers
- **Backtest walk-forward** com Monte Carlo e análise de regime
- **Dashboard web** com curva de equity, drawdown e expectancy
- **Notificações Telegram** estruturadas

---

## Arquitetura

```
main.py              ← Entrypoint: scheduler, threads, orquestração
├── bot.py           ← Motor principal (estado, cooldowns, circuit breaker)
├── signals.py       ← Pipeline de sinais (técnico → filtros → score)
├── analysis.py      ← Dados e indicadores (cache, integridade)
├── risk.py          ← Position sizing, limites de perda, exposição
├── portfolio.py     ← Gestão de carteira, correlação, tiers
├── ai_validator.py  ← Validação Gemini (prompt versionado, auditável)
├── news_filter.py   ← Bloqueio por notícias de alto impacto
├── cot_filter.py    ← Bias institucional CFTC/COT
├── backtester.py    ← Walk-forward, Monte Carlo, análise de regime
├── performance.py   ← Métricas: Sharpe, Sortino, Calmar, expectancy
├── db.py            ← SQLite com migrações versionadas e atomicidade
├── api.py           ← REST API Flask com autenticação
├── telegram_hedgefund.py ← Templates Telegram padronizados
└── config.py        ← Configuração tipada com validação rígida
```

---

## Instalação

```bash
git clone <repo> && cd crypto-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # edite com suas chaves
```

---

## Variáveis de Ambiente

| Variável | Obrigatório | Descrição |
|---|---|---|
| `TELEGRAM_TOKEN` | ✅ | Token do bot Telegram |
| `TELEGRAM_CHAT_ID` | ✅ | ID do chat/grupo de sinais |
| `TWELVE_DATA_API_KEY` | ✅ | Chave Twelve Data (dados de mercado) |
| `GEMINI_API_KEY` | ⚠️ Recomendado | Chave Google Gemini |
| `DASHBOARD_API_TOKEN` | ⚠️ Produção | Token de auth do dashboard |
| `NTFY_TOPIC` | ❌ Opcional | Push via ntfy.sh |
| `BACKUP_REMOTE_URL` | ❌ Opcional | URL S3/Supabase para backup |
| `DEFAULT_LEVERAGE` | ❌ Opcional | Alavancagem padrão (default: 500) |
| `INITIAL_BALANCE` | ❌ Opcional | Saldo simulado inicial (default: 1000) |
| `DB_PATH` | ❌ Opcional | Caminho SQLite (default: bot_state.db) |

Gere o token do dashboard: `python -c "import secrets; print(secrets.token_hex(32))"`

---

## Execução

```bash
python main.py                                           # modo normal
python backtester.py --symbol EURUSD --walk-forward      # backtest walk-forward
python backtester.py --symbol XAUUSD --monte-carlo       # Monte Carlo
python genetic_optimizer.py --symbol EURUSD --generations 50
pytest                                                   # testes
```

---

## Risco e Proteções

```
Nível 1 — Por trade:     Stop Loss (ATR-based), Take Profit, expiração de sinal
Nível 2 — Por ativo:     Cooldown após loss, máximo de tentativas
Nível 3 — Por sessão:    Filtro de liquidez, notícias, gap fim de semana
Nível 4 — Por carteira:  Correlação, exposição total, sinais simultâneos
Nível 5 — Global:        Perda diária → pausa; perda semanal → circuit breaker
```

---

## Backtesting

```bash
# Walk-forward (mais robusto — separa treino e validação)
python backtester.py --symbol EURUSD --bars 2000 --walk-forward

# Monte Carlo (robustez por permutação de sequência de trades)
python backtester.py --symbol XAUUSD --monte-carlo --simulations 1000

# Out-of-sample comparison + relatório de overfitting
python backtester.py --symbol GBPUSD --oos-report
```

---

## Dashboard

Acesse `http://localhost:5000` (local) ou URL do Railway.  
Autenticação obrigatória em produção via `DASHBOARD_API_TOKEN`.

---

## Testes

```bash
pytest                          # todos
pytest tests/test_risk.py -v    # risco
pytest tests/test_performance.py
pytest tests/test_backtester.py
```

---

## Deploy Railway

1. Fork o repositório → conecte ao Railway
2. Configure variáveis em **Variables** (nunca commite `.env`)
3. `DB_PATH=/data/bot_state.db` (volume persistente)
4. `Procfile` já configurado: `web: python main.py`

> `bot_state.db` e `bot_app.log` estão no `.gitignore` — não versione esses arquivos.

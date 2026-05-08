# Sniper Bot — FX & Gold Signal Engine Simplificado

> **Sinalizador apenas.** O bot não executa ordens reais em corretora. Nenhum bot consegue garantir 10–15% ao mês; essa versão foi ajustada para reduzir ruído, melhorar disciplina e facilitar backtests.

## O que mudou

A lógica antiga estava saturada: combinava EMA, RSI, MACD, Bollinger, FVG, Order Block, liquidity sweep, COT, IA, regime dinâmico e múltiplos filtros. Isso aumentava conflitos internos e sinais inconsistentes.

Esta versão usa apenas quatro indicadores no sinal ao vivo:

1. **EMA50 + EMA200** — direção da tendência.
2. **RSI14** — momentum e zona operacional.
3. **ATR14** — stop, alvo e filtro de volatilidade.
4. **ADX14** — força mínima da tendência.

O restante fica como proteção operacional, não como gerador de sinal: sessão principal, notícias de alto impacto, fim de semana/gap, cooldown e correlação.

## Regra de sinal

### Compra

- Preço acima da EMA200.
- EMA50 acima da EMA200.
- H4/D1 não estão contra a direção.
- RSI entre 50 e 68.
- Preço próximo da EMA50, sem estar esticado demais.
- ATR saudável.
- ADX acima do mínimo configurado.

### Venda

- Preço abaixo da EMA200.
- EMA50 abaixo da EMA200.
- H4/D1 não estão contra a direção.
- RSI entre 32 e 50.
- Preço próximo da EMA50, sem estar esticado demais.
- ATR saudável.
- ADX acima do mínimo configurado.

## Gestão de risco padrão

- Stop Loss: `1.5 × ATR`.
- Take Profit: `3.0 × ATR`.
- Relação risco-retorno aproximada: `1:2`.
- Risco de referência: `1%` por trade.
- Notícias de alto impacto: bloqueadas por padrão.
- Sessões fora de liquidez: bloqueadas por padrão.

## Arquivos principais

```text
main.py        Entrypoint do bot
signals.py     Motor simplificado de sinais
analysis.py    Dados, EMA50/EMA200, RSI, ATR, ADX e MTF
config.py      Parâmetros e proteções
bot.py         Estado, cooldown, notificações e monitoramento
backtester.py  Backtests e relatórios
risk.py        Gestão de risco
```

## Instalação

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Configure no `.env`:

```text
TELEGRAM_TOKEN=
TELEGRAM_CHAT_ID=
TWELVE_DATA_API_KEY=
DASHBOARD_API_TOKEN=
```

## Execução

```bash
python main.py
```

## Backtest

```bash
python backtester.py --symbol EURUSD --walk-forward
python backtester.py --symbol XAUUSD --monte-carlo
pytest
```

## Parâmetros importantes

Estão em `config.py` e `strategy_settings.json`:

```text
SIMPLE_MIN_SCORE = 8
ADX_MIN_TREND = 18
RSI_BUY_MIN = 50
RSI_BUY_MAX = 68
RSI_SELL_MIN = 32
RSI_SELL_MAX = 50
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0
MIN_RR = 1.8
RISK_PERCENT_PER_TRADE = 1.0
```

## Observação importante

Meta de 10–15% ao mês em Forex normalmente exige alavancagem e risco elevados. Use essa versão como base disciplinada para backtest, forward test em conta demo e ajuste por par antes de considerar capital real.

## Backtest Lab multi-anos

Esta versão inclui um laboratório de backtest para testar várias configurações usando anos de candles OHLC em CSV, sem enviar ordens reais e sem depender do Telegram.

### Rodar pelo terminal

```bash
python backtest_lab.py dados/EURUSD_M15.csv --symbol EURUSD --balance 1000 --grid quick --top 20 --out reports
```

Busca mais ampla:

```bash
python backtest_lab.py dados/EURUSD_M15.csv --symbol EURUSD --balance 1000 --grid deep --top 30 --out reports
```

Arquivos gerados em `reports/`:

- `*_ranking.csv`: ranking das configurações testadas.
- `*_top.csv`: melhores configurações.
- `*_yearly_best.csv`: consistência anual da melhor configuração.
- `*_summary.json`: resumo completo.

### Rodar pelo Telegram

1. Envie `/lab EURUSD`.
2. Envie o CSV histórico do par.
3. O bot responde com a melhor configuração, retorno, drawdown, profit factor e resultado anual.

### Testes simulados do Telegram

O arquivo `telegram_testkit.py` simula `sendMessage`, `getUpdates`, upload/download de CSV e falhas transitórias, sem usar internet. Rode:

```bash
pytest -q
```

Resultado validado nesta build: `51 passed`.

> Aviso: backtest não garante lucro futuro. Use os resultados para filtrar configurações e faça forward test em conta demo antes de qualquer operação real.

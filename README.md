# Professional Signal Bot

Base profissional para bot de sinais / paper trading / execução futura em Forex e Gold.

## O que tem
- arquitetura modular
- estratégia com filtros de tendência, momentum e candle pattern
- gestão de risco
- backtest simples
- API Flask para dashboard
- persistência em JSON
- integração com Twelve Data para candles

## Como rodar localmente
```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
export TWELVEDATA_API_KEY="SUA_CHAVE"
python main.py
```

## Rotas
- `GET /health`
- `GET /status`
- `GET /metrics`
- `POST /run-once`
- `POST /start`
- `POST /stop`
- `POST /config`

## Modos
- `signals`: apenas gera sinais
- `paper`: gera sinais e simula trades
- `execution`: pronto para integrar com broker adapter

## Próximo passo
Conectar um `BrokerAdapter` real da corretora escolhida e ajustar o cálculo de volume ao contrato do ativo.

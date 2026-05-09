# Forex Signal Bot

Bot modular de sinais Forex com filtros, gerenciamento de risco, backtest, ML opcional, Telegram e dashboard.

## Railway
Use o comando de start:

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

## Rodar local
```bash
cp .env.example .env
pip install -r requirements.txt
python main.py
```

## Healthcheck
`GET /health`

## Sinais recentes
`GET /signals`

## Dashboard
```bash
streamlit run dashboard/app.py
```

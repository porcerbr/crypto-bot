# Sniper Bot

Bot de sinais Forex/Ouro com análise técnica, SMC, validação por IA, gestão de risco e dashboard HTTP.

## Deploy
Defina as variáveis de ambiente obrigatórias:
- `TELEGRAM_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TWELVE_DATA_API_KEY`
- `GEMINI_API_KEY`
- `NTFY_TOPIC`

Depois rode:
```bash
python main.py
```

## Rotas úteis
- `/api/health`
- `/api/status`
- `/api/metrics`
- `/api/performance`
- `/api/equity_curve`
- `/api/logs`
- `/api/ai_params`

## Observação
Este projeto é sinalizador: não envia ordens para corretora.

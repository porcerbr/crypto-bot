# Dashboard Tickmill Sniper Bot - Guia de Integração

## 📋 O que foi criado

Um **dashboard web profissional** em dark mode que se integra com seu bot Flask existente, permitindo:

- ✅ Monitorar saldo, equity, margem e P&L em tempo real
- ✅ Configurar alavancagem, ATR, Telegram e outros parâmetros
- ✅ Ver operações abertas e histórico de trades
- ✅ Radar de sinais com confluência
- ✅ Logs de atividades
- ✅ Iniciar/parar bot
- ✅ Fechar trades manualmente

## 🚀 Como integrar (Railway)

### Passo 1: Copiar arquivos

```bash
# Copie os arquivos para seu repositório
cp dashboard.html /seu/repo/
cp flask_extensions.py /seu/repo/
```

### Passo 2: Modificar main.py

Adicione estas linhas **após criar a app Flask**:

```python
# No início do arquivo (imports)
from flask_extensions import register_dashboard_routes

# Após criar app = Flask(__name__)
register_dashboard_routes(app, bot)
```

### Passo 3: Atualizar requirements.txt

Certifique-se que tem:
```
Flask==2.3.0
Flask-CORS==4.0.0
pandas==2.0.0
requests==2.31.0
```

### Passo 4: Deploy no Railway

```bash
git add .
git commit -m "Add dashboard integration"
git push
```

O Railway detectará as mudanças e fará redeploy automaticamente.

## 🌐 Acessar o Dashboard

Após deploy:

```
https://seu-app.railway.app/dashboard
```

## 📊 Funcionalidades

### Dashboard Principal
- **Saldo**: Seu saldo atual em USD
- **Equity**: Saldo + P&L não realizado
- **Margem Livre**: Disponível para novas operações
- **P&L Líquido**: Lucro/prejuízo total
- **Alavancagem**: Configuração atual
- **Trades Abertos**: Número de operações ativas

### Abas

1. **Operações Abertas**
   - Tabela com todos os trades ativos
   - Símbolo, direção, lote, entrada, SL, TP
   - P&L em tempo real (verde/vermelho)
   - Botão para fechar manualmente

2. **Histórico**
   - Todos os trades encerrados
   - Filtros por ativo e resultado
   - Comissão deduzida

3. **Radar de Sinais**
   - Ativos com maior confluência
   - Score de entrada
   - Direção sugerida (BUY/SELL)

4. **Logs**
   - Últimas ações do bot
   - Filtros por nível (info, warning, error)

### Configurações

Clique em **⚙ Configurações** para:

- **Alavancagem Padrão**: 1-500x
- **ATR Multiplicador SL**: Ajuste stop loss
- **ATR Multiplicador TP**: Ajuste take profit
- **ATR Multiplicador Trail**: Trailing stop
- **Risco por Trade**: % do saldo
- **Bot Token Telegram**: Para notificações
- **Chat ID Telegram**: ID do chat
- **Timeframe**: 1m a 4h
- **Ativos Monitorados**: Selecione quais monitorar

## 🔧 Estrutura de Arquivos

```
seu-repo/
├── main.py                    (seu bot original)
├── dashboard.html             (novo - dashboard UI)
├── flask_extensions.py        (novo - rotas Flask)
├── bot_settings.json          (gerado automaticamente)
└── requirements.txt           (atualizar)
```

## 📡 Endpoints da API

O dashboard usa estes endpoints (já existentes ou novos):

```
GET  /api/status              → Status do bot, saldo, trades
GET  /api/config              → Configurações atuais
GET  /api/history             → Histórico de trades
GET  /api/signals             → Sinais do radar
POST /api/settings            → Salvar configurações
POST /api/start               → Iniciar bot
POST /api/stop                → Parar bot
POST /api/close_trade         → Fechar trade
POST /api/test_telegram       → Testar Telegram
```

## 🎨 Design

- **Dark Mode**: Tema profissional em tons de azul/cinza
- **Cores**: Verde (lucro), Vermelho (prejuízo)
- **Responsivo**: Funciona em desktop, tablet e mobile
- **Atualização Automática**: Dados atualizados a cada 5 segundos

## 🐛 Troubleshooting

### Dashboard não carrega
- Verifique se `/dashboard` está acessível
- Confirme que `flask_extensions.py` foi importado
- Veja os logs do Railway

### Configurações não salvam
- Verifique se `bot_settings.json` tem permissão de escrita
- Em Railway, use variáveis de ambiente em vez de arquivo

### Dados não atualizam
- Verifique conexão com `/api/status`
- Confirme que o bot está rodando
- Veja console do navegador (F12)

## 💾 Persistência de Configurações

Por padrão, as configurações são salvas em `bot_settings.json`.

**Para Railway (melhor prática):**

Modifique `flask_extensions.py` para usar variáveis de ambiente:

```python
# Em vez de arquivo JSON
os.environ["DEFAULT_LEVERAGE"] = str(leverage)
os.environ["ATR_MULT_SL"] = str(atr_mult_sl)
# etc...
```

## 🔐 Segurança

- ✅ Senhas Telegram não são exibidas (mascaradas com ***)
- ✅ CORS habilitado para o dashboard
- ✅ Validação de entrada nos endpoints
- ✅ Sem exposição de dados sensíveis

## 📝 Próximos Passos

1. ✅ Integrar dashboard
2. ✅ Testar em desenvolvimento
3. ✅ Deploy no Railway
4. ✅ Monitorar em produção

## 📞 Suporte

Se tiver problemas:

1. Verifique os logs do Railway
2. Confirme que Flask-CORS está instalado
3. Teste os endpoints manualmente com curl
4. Veja o console do navegador (F12)

---

**Versão**: 1.0  
**Data**: Abril 2026  
**Plataforma**: Railway + Flask

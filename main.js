/* Trading Bot Pro - Dashboard Frontend */

const socket = io();

// Estado local
let currentState = {};
let uptimeInterval = null;

// Conexão Socket.IO
socket.on("connect", () => {
    console.log("Conectado ao servidor");
    addLog("Conectado ao dashboard em tempo real", "info");
});

socket.on("disconnect", () => {
    addLog("Desconectado do servidor", "error");
});

socket.on("state_update", (state) => {
    currentState = state;
    updateUI(state);
});

// Atualização completa da UI
function updateUI(state) {
    // Status
    const statusEl = document.getElementById("status-badge");
    statusEl.className = `status-badge ${state.status}`;
    statusEl.textContent = translateStatus(state.status);

    // Símbolo e update
    document.getElementById("symbol").textContent = state.symbol || "---";
    document.getElementById("last-update").textContent = state.last_update 
        ? new Date(state.last_update).toLocaleTimeString("pt-BR") 
        : "---";

    // P&L
    setValue("daily-pnl", state.daily_pnl, true);
    setValue("weekly-pnl", state.weekly_pnl, true);
    setValue("monthly-pnl", state.monthly_pnl, true);

    // Win/Loss
    document.getElementById("win-rate").textContent = state.win_rate.toFixed(1) + "%";
    document.getElementById("win-rate").className = `card-value ${state.win_rate >= 50 ? "positive" : "negative"}`;
    document.getElementById("win-count").textContent = state.win_count;
    document.getElementById("loss-count").textContent = state.loss_count;

    // Sinal
    if (state.last_signal) {
        const sig = state.last_signal;
        const dirEl = document.getElementById("signal-direction");
        dirEl.className = `signal-direction ${sig.direction}`;
        dirEl.textContent = sig.direction === "LONG" ? "COMPRA" : sig.direction === "SHORT" ? "VENDA" : "AGUARDANDO";

        document.getElementById("signal-reason").textContent = sig.reason || "Sem justificativa";
        document.getElementById("signal-score-text").textContent = `Score: ${sig.score}`;

        const fill = document.getElementById("score-fill");
        fill.style.width = `${Math.min(sig.score, 100)}%`;
        fill.className = `score-fill ${sig.score >= 70 ? "high" : sig.score >= 50 ? "medium" : "low"}`;
    }

    // Filtros
    const filtersEl = document.getElementById("filters-list");
    if (state.active_filters && state.active_filters.length > 0) {
        filtersEl.innerHTML = state.active_filters.map(f => 
            `<span class="filter-tag">${translateFilter(f)}</span>`
        ).join("");
        filtersEl.classList.remove("empty");
    } else {
        filtersEl.innerHTML = "";
        filtersEl.classList.add("empty");
    }

    // Logs/Alertas
    if (state.alerts && state.alerts.length > 0) {
        state.alerts.slice(-5).forEach(alert => addLog(alert, "alert"));
    }
    if (state.recent_errors && state.recent_errors.length > 0) {
        state.recent_errors.slice(-3).forEach(err => addLog(err, "error"));
    }

    // Uptime
    startUptime(state.uptime_seconds);

    // Atualizar trades
    loadTrades();
}

function setValue(id, value, isCurrency = false) {
    const el = document.getElementById(id);
    const formatted = isCurrency ? formatCurrency(value) : value;
    el.textContent = formatted;
    el.className = `card-value ${value > 0 ? "positive" : value < 0 ? "negative" : "neutral"}`;
}

function formatCurrency(val) {
    return "R$ " + val.toLocaleString("pt-BR", {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function translateStatus(status) {
    const map = {
        "running": "Executando",
        "stopped": "Parado",
        "paused": "Pausado",
        "error": "Erro",
        "starting": "Iniciando"
    };
    return map[status] || status;
}

function translateFilter(filter) {
    const map = {
        "fora_horario": "Fora de Horário",
        "volatilidade_alta": "Volatilidade Alta",
        "volume_baixo": "Volume Baixo",
        "exposicao_maxima": "Exposição Máxima",
        "max_operacoes": "Máx. Operações"
    };
    return map[filter] || filter;
}

function addLog(message, type = "info") {
    const container = document.getElementById("logs-container");
    const entry = document.createElement("div");
    entry.className = `log-entry ${type}`;
    const time = new Date().toLocaleTimeString("pt-BR");
    // Extrair timestamp se existir no início
    const cleanMsg = message.replace(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z?\s*-\s*/, "");
    entry.textContent = `[${time}] ${cleanMsg}`;
    container.insertBefore(entry, container.firstChild);

    // Limitar a 50 entradas
    while (container.children.length > 50) {
        container.removeChild(container.lastChild);
    }
}

function startUptime(seconds) {
    if (uptimeInterval) clearInterval(uptimeInterval);
    let current = seconds;
    const el = document.getElementById("uptime");
    const update = () => {
        current++;
        const h = Math.floor(current / 3600);
        const m = Math.floor((current % 3600) / 60);
        const s = current % 60;
        el.textContent = h > 0 ? `${h}h ${m}m ${s}s` : m > 0 ? `${m}m ${s}s` : `${s}s`;
    };
    update();
    uptimeInterval = setInterval(update, 1000);
}

function sendCommand(cmd) {
    fetch(`/api/${cmd}`)
        .then(r => r.json())
        .then(data => {
            addLog(`Comando: ${cmd} - ${data.status}`, "info");
        })
        .catch(err => {
            addLog(`Erro no comando ${cmd}: ${err}`, "error");
        });
}

function loadTrades() {
    fetch("/api/trades")
        .then(r => r.json())
        .then(trades => {
            const tbody = document.getElementById("trades-body");
            if (!trades || trades.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-secondary)">Nenhum trade registrado</td></tr>`;
                return;
            }
            tbody.innerHTML = trades.slice(0, 20).map(t => {
                const time = t.timestamp ? new Date(t.timestamp).toLocaleString("pt-BR") : "---";
                const pnlClass = t.pnl > 0 ? "positive" : t.pnl < 0 ? "negative" : "neutral";
                const statusClass = t.status === "CLOSED_WIN" ? "badge-win" : t.status === "CLOSED_LOSS" ? "badge-loss" : "badge-open";
                const statusText = t.status === "CLOSED_WIN" ? "WIN" : t.status === "CLOSED_LOSS" ? "LOSS" : "OPEN";
                return `
                    <tr>
                        <td>${time}</td>
                        <td>${t.direction}</td>
                        <td>${parseFloat(t.entry_price).toFixed(2)}</td>
                        <td>${t.score}</td>
                        <td class="${pnlClass}">${t.pnl > 0 ? "+" : ""}${parseFloat(t.pnl).toFixed(2)}</td>
                        <td><span class="badge ${statusClass}">${statusText}</span></td>
                    </tr>
                `;
            }).join("");
        })
        .catch(() => {});
}

// Carregar estado inicial
fetch("/api/state")
    .then(r => r.json())
    .then(state => updateUI(state))
    .catch(() => addLog("Falha ao carregar estado inicial", "error"));

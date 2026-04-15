const summaryCards = document.getElementById("summary-cards");
const chart = document.getElementById("month-chart");
const tooltip = document.getElementById("chart-tooltip");
const tradeRows = document.getElementById("trade-rows");
const tradeCount = document.getElementById("trade-count");
const selectionCaption = document.getElementById("selection-caption");
const monthFilter = document.getElementById("month-filter");
const setupFilter = document.getElementById("setup-filter");
const sideFilter = document.getElementById("side-filter");
const searchFilter = document.getElementById("search-filter");
const clearMonthButton = document.getElementById("clear-month");

let monthlyData = [];
let activeMonth = "";

const currencyFormat = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const percentFormat = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatDate(dateString) {
  if (!dateString) return "—";
  const date = new Date(dateString);
  if (Number.isNaN(date.getTime())) return dateString;
  return date.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatMonth(month) {
  if (!month) return "";
  const date = new Date(`${month}-01T00:00:00`);
  return date.toLocaleDateString("en-US", { year: "numeric", month: "short" });
}

function formatCurrency(value) {
  return currencyFormat.format(value || 0);
}

function formatPercent(value) {
  return percentFormat.format(value || 0);
}

function statCard(label, value, className = "") {
  return `
    <article class="stat-card">
      <span>${label}</span>
      <strong class="${className}">${value}</strong>
    </article>
  `;
}

function renderSummary(summary) {
  summaryCards.innerHTML = [
    statCard("Net P&L", formatCurrency(summary.net_pnl), summary.net_pnl >= 0 ? "positive" : "negative"),
    statCard("Portfolio Return", formatPercent(summary.portfolio_return), summary.portfolio_return >= 0 ? "positive" : "negative"),
    statCard("Trades", String(summary.trade_count)),
    statCard("Win Rate", formatPercent(summary.win_rate)),
    statCard("Average Win", formatCurrency(summary.average_win), "positive"),
    statCard("Average Loss", formatCurrency(summary.average_loss), "negative"),
    statCard("Best Trade", formatCurrency(summary.best_trade), "positive"),
    statCard("Worst Trade", formatCurrency(summary.worst_trade), "negative"),
    statCard("Median Hold", `${summary.median_holding_days.toFixed(1)} days`),
  ].join("");
}

function fillSelect(select, values, formatter = (value) => value) {
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = formatter(value);
    select.append(option);
  }
}

function renderChart(months) {
  monthlyData = months;
  chart.innerHTML = "";

  const maxMagnitude = Math.max(...months.map((item) => Math.abs(item.portfolio_return || 0)), 0.01);

  for (const item of months) {
    const column = document.createElement("article");
    column.className = "chart-column";

    const barWrap = document.createElement("div");
    barWrap.className = "chart-bar-wrap";

    const bar = document.createElement("button");
    bar.type = "button";
    bar.className = "chart-bar";
    if (activeMonth === item.month) {
      bar.classList.add("active");
    }

    const height = Math.max((Math.abs(item.portfolio_return || 0) / maxMagnitude) * 220, 12);
    bar.style.height = `${height}px`;
    bar.style.background = item.portfolio_return >= 0
      ? "linear-gradient(180deg, rgba(11, 122, 83, 0.72), rgba(11, 122, 83, 0.98))"
      : "linear-gradient(180deg, rgba(180, 66, 46, 0.72), rgba(180, 66, 46, 0.98))";
    bar.setAttribute("aria-label", `${formatMonth(item.month)} ${formatPercent(item.portfolio_return)}`);

    const label = document.createElement("div");
    label.className = "chart-bar-label";
    label.innerHTML = `<strong>${formatMonth(item.month)}</strong><div class="chart-bar-value">${formatPercent(item.portfolio_return)}</div>`;

    const axis = document.createElement("div");
    axis.className = "chart-axis";

    bar.addEventListener("click", () => {
      activeMonth = activeMonth === item.month ? "" : item.month;
      monthFilter.value = activeMonth;
      clearMonthButton.hidden = !activeMonth;
      renderChart(monthlyData);
      fetchTrades();
    });

    bar.addEventListener("mousemove", (event) => {
      tooltip.hidden = false;
      tooltip.style.left = `${event.pageX + 12}px`;
      tooltip.style.top = `${event.pageY - 18}px`;
      tooltip.innerHTML = `
        <strong>${formatMonth(item.month)}</strong><br>
        Return: ${formatPercent(item.portfolio_return)}<br>
        Net P&amp;L: ${formatCurrency(item.net_pnl)}<br>
        Trades: ${item.trades}<br>
        Wins / Losses: ${item.wins} / ${item.losses}
      `;
    });

    bar.addEventListener("mouseleave", () => {
      tooltip.hidden = true;
    });

    barWrap.append(bar);
    column.append(barWrap, axis, label);
    chart.append(column);
  }
}

function buildQuery() {
  const params = new URLSearchParams();
  if (monthFilter.value) params.set("month", monthFilter.value);
  if (setupFilter.value) params.set("setup", setupFilter.value);
  if (sideFilter.value) params.set("side", sideFilter.value);
  if (searchFilter.value.trim()) params.set("search", searchFilter.value.trim());
  return params.toString();
}

function renderTrades(payload) {
  tradeCount.textContent = `${payload.count} trade${payload.count === 1 ? "" : "s"}`;

  const parts = [];
  if (monthFilter.value) parts.push(formatMonth(monthFilter.value));
  if (setupFilter.value) parts.push(setupFilter.value);
  if (sideFilter.value) parts.push(sideFilter.value);
  if (searchFilter.value.trim()) parts.push(`search "${searchFilter.value.trim()}"`);
  selectionCaption.textContent = parts.length ? `Filtered by ${parts.join(" · ")}` : "Showing all trades";

  tradeRows.innerHTML = payload.trades.map((trade) => `
    <tr>
      <td>${formatDate(trade.exit_date)}</td>
      <td><strong>${trade.ticker || "—"}</strong></td>
      <td>${trade.side || "—"}</td>
      <td>${trade.setup || "—"}</td>
      <td>${formatDate(trade.entry_date)}</td>
      <td>${trade.entry_price == null ? "—" : trade.entry_price.toFixed(2)}</td>
      <td>${trade.exit_price == null ? "—" : trade.exit_price.toFixed(2)}</td>
      <td class="${trade.net_pnl >= 0 ? "positive" : "negative"}">${formatCurrency(trade.net_pnl)}</td>
      <td class="${trade.portfolio_return >= 0 ? "positive" : "negative"}">${formatPercent(trade.portfolio_return)}</td>
      <td>${trade.holding_days == null ? "—" : `${trade.holding_days}d`}</td>
      <td class="notes-cell">${trade.notes || trade.technicals || trade.fundamentals || "—"}</td>
    </tr>
  `).join("");
}

async function fetchSummary() {
  const response = await fetch("/api/summary");
  const payload = await response.json();
  renderSummary(payload.summary);
  fillSelect(monthFilter, payload.filters.months, formatMonth);
  fillSelect(setupFilter, payload.filters.setups);
  fillSelect(sideFilter, payload.filters.sides);
  renderChart(payload.monthly);
}

async function fetchTrades() {
  const response = await fetch(`/api/trades?${buildQuery()}`);
  const payload = await response.json();
  renderTrades(payload);
}

function attachEvents() {
  monthFilter.addEventListener("change", () => {
    activeMonth = monthFilter.value;
    clearMonthButton.hidden = !activeMonth;
    renderChart(monthlyData);
    fetchTrades();
  });

  setupFilter.addEventListener("change", fetchTrades);
  sideFilter.addEventListener("change", fetchTrades);
  searchFilter.addEventListener("input", fetchTrades);
  clearMonthButton.addEventListener("click", () => {
    activeMonth = "";
    monthFilter.value = "";
    clearMonthButton.hidden = true;
    renderChart(monthlyData);
    fetchTrades();
  });
}

async function init() {
  await fetchSummary();
  attachEvents();
  await fetchTrades();
}

init().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;font-family:monospace;">Failed to load dashboard:\n${error}</pre>`;
});

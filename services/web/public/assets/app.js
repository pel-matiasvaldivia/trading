import { barChart, formatDate, formatNumber, lineChart } from "./charts.js";

const TOKEN_KEY = "tradingbot-token";
const $ = (id) => document.getElementById(id);

function readToken() {
  try { return localStorage.getItem(TOKEN_KEY) || ""; } catch (e) { return ""; }
}

function writeToken(value) {
  try { localStorage.setItem(TOKEN_KEY, value); } catch (e) { /* modo privado */ }
}

async function api(path) {
  const response = await fetch(`/api${path}`, {
    headers: { "X-API-Token": readToken() },
  });
  if (response.status === 401) {
    const error = new Error("token invalido");
    error.unauthorized = true;
    throw error;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function setConnection(state, text) {
  const node = $("conn");
  node.className = `status status-${state}`;
  node.querySelector(".icon").textContent =
    state === "good" ? "✓" : state === "critical" ? "✕" : "▸";
  $("conn-text").textContent = text;
}

function table(node, columns, rows, emptyMessage) {
  if (!rows.length) {
    node.innerHTML = `<tbody><tr><td class="empty">${emptyMessage}</td></tr></tbody>`;
    return;
  }
  const head = columns
    .map((c) => `<th${c.num ? ' class="num"' : ""}>${c.label}</th>`)
    .join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((c) => `<td${c.num ? ' class="num"' : ""}>${c.render(row)}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  node.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
}

// --------------------------------------------------------------------------

async function loadStatus() {
  const status = await api("/status");
  $("stat-capital").textContent = formatNumber(status.starting_cash);
  $("stat-book").textContent = `libro ${status.book}`;
  $("stat-roundtrip").textContent = `${formatNumber(status.costs.breakeven_move_pct)} %`;
  $("stat-percost").textContent = formatNumber(status.cost_per_round_trip, 3);

  const mode = $("stat-mode");
  mode.textContent = status.live_trading ? "EN VIVO" : "Papel";
  mode.className = `value ${status.live_trading ? "neg" : ""}`;
  $("stat-phase").textContent = `fase ${status.phase} de 3`;

  const monthly = (status.cost_per_round_trip * 10) / status.starting_cash * 100;
  $("status-lede").textContent =
    `Diez operaciones mensuales cuestan ${formatNumber(monthly, 1)} % del capital ` +
    `solo en comisiones, spread y slippage.`;
}

async function loadCoverage() {
  const data = await api("/coverage");
  const candles = data.candles;

  barChart($("coverage-chart"), candles.map((row) => ({
    label: `${row.book} ${row.tf_label}`,
    value: row.n,
  })));

  const totalTrades = data.books.reduce((sum, b) => sum + b.trades, 0);
  const totalCandles = candles.reduce((sum, c) => sum + c.n, 0);
  if (!candles.length) {
    $("coverage-caption").textContent =
      "Todavia no hay datos. Correr el collector, o cargar datos sinteticos con 'demo'.";
  } else if (totalTrades === 0) {
    // Velas sin trades crudos: son datos sinteticos cargados con 'demo'.
    // Decir "0 trades" a secas haria pensar que falta algo.
    $("coverage-caption").textContent =
      `${formatNumber(totalCandles, 0)} velas, sin trades crudos: datos sinteticos. ` +
      `No sirven para evaluar estrategias.`;
  } else {
    $("coverage-caption").textContent =
      `${formatNumber(totalCandles, 0)} velas construidas desde ` +
      `${formatNumber(totalTrades, 0)} trades en ${data.books.length} libro(s).`;
  }

  if (candles.length) {
    const last = Math.max(...candles.map((c) => c.last_ts));
    $("coverage-range").textContent = `ultimo dato: ${formatDate(last)}`;
  }

  table($("coverage-table"),
    [
      { label: "Libro", render: (r) => r.book },
      { label: "TF", render: (r) => r.tf_label },
      { label: "Velas", num: true, render: (r) => formatNumber(r.n, 0) },
      { label: "Desde", render: (r) => formatDate(r.first_ts) },
      { label: "Hasta", render: (r) => formatDate(r.last_ts) },
    ],
    candles, "Sin velas almacenadas.");
}

async function loadRun(runId) {
  const [curve, fills, rejects] = await Promise.all([
    api(`/runs/${encodeURIComponent(runId)}/equity`).catch(() => []),
    api(`/fills?run_id=${encodeURIComponent(runId)}&limit=100`),
    api(`/rejections?run_id=${encodeURIComponent(runId)}&limit=100`),
  ]);

  const points = curve.map((p) => ({ x: p.ts, y: p.equity }));
  lineChart($("equity-chart"), points, { valueLabel: "Equity" });

  if (points.length > 1) {
    const start = points[0].y;
    const end = points[points.length - 1].y;
    const change = ((end - start) / start) * 100;
    const sign = change >= 0 ? "+" : "";
    $("equity-caption").textContent =
      `${points.length} puntos · de ${formatNumber(start)} a ${formatNumber(end)} ` +
      `(${sign}${formatNumber(change)} %).`;
  } else {
    $("equity-caption").textContent = "Sin curva registrada para esta corrida.";
  }

  table($("equity-table"),
    [
      { label: "Momento", render: (r) => formatDate(r.ts) },
      { label: "Equity", num: true, render: (r) => formatNumber(r.equity) },
    ],
    curve, "Sin puntos de equity.");

  table($("fills-table"),
    [
      { label: "Momento", render: (r) => formatDate(r.ts) },
      { label: "Lado", render: (r) => (r.side === "buy" ? "compra" : "venta") },
      { label: "Cantidad", num: true, render: (r) => formatNumber(r.amount, 6) },
      { label: "Precio", num: true, render: (r) => formatNumber(r.price, 4) },
      { label: "Comision", num: true, render: (r) => formatNumber(r.fee, 4) },
    ],
    fills, "Sin operaciones en esta corrida.");

  table($("rejects-table"),
    [
      { label: "Momento", render: (r) => formatDate(r.ts) },
      { label: "Motivo", render: (r) => r.detail || "—" },
    ],
    rejects, "Ningun rechazo. La estrategia pidio solo cosas ejecutables.");
}

async function loadRuns() {
  const runs = await api("/runs?limit=50");
  const select = $("run-select");
  if (!runs.length) {
    select.innerHTML = '<option>sin corridas registradas</option>';
    lineChart($("equity-chart"), []);
    $("equity-caption").textContent =
      "No hay corridas en el journal. Correr un backtest para poblarlo.";
    return;
  }
  select.innerHTML = runs
    .map((r) => `<option value="${r.run_id}">${r.run_id} · ${r.fills} ops · ${r.rejects} rechazos</option>`)
    .join("");
  select.onchange = () => loadRun(select.value);
  await loadRun(runs[0].run_id);
}

async function boot() {
  $("auth-screen").classList.add("hidden");
  $("app").classList.remove("hidden");
  setConnection("warning", "cargando…");
  try {
    await Promise.all([loadStatus(), loadCoverage()]);
    await loadRuns();
    setConnection("good", "conectado");
  } catch (error) {
    if (error.unauthorized) { showAuth("Token rechazado por la API."); return; }
    setConnection("critical", error.message);
  }
}

function showAuth(message) {
  $("app").classList.add("hidden");
  $("auth-screen").classList.remove("hidden");
  setConnection("critical", "sin autenticar");
  if (message) {
    const node = $("auth-error");
    node.textContent = message;
    node.classList.remove("hidden");
  }
}

$("token-save").addEventListener("click", () => {
  writeToken($("token-input").value.trim());
  boot();
});
$("token-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter") $("token-save").click();
});

// La API puede no tener token configurado; se intenta entrar directamente y
// solo se pide credencial si responde 401.
boot();

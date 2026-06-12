"""GoldEye web dashboard — served from the Fly.io machine.

Exposes:
  GET /            — HTML dashboard (auto-refreshes every 60s)
  GET /api/state   — current bot state (balance, open signal, last scan)
  GET /api/signals — all signals from signals.csv as JSON
  GET /api/stats   — summary stats + balance chart data
"""

from datetime import datetime, timezone

from flask import Flask, jsonify

from goldeye import storage

app = Flask(__name__)


@app.route("/")
def dashboard():
    return _DASHBOARD_HTML, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/api/state")
def api_state():
    state = storage.load_state()
    ts = state.get("last_scan_ts", 0)
    if ts:
        state["last_scan_human"] = datetime.fromtimestamp(
            ts, timezone.utc
        ).strftime("%d %b %H:%M UTC")
    return jsonify(state)


@app.route("/api/signals")
def api_signals():
    return jsonify(storage.read_signals())


@app.route("/api/stats")
def api_stats():
    rows = storage.read_signals()
    state = storage.load_state()
    closed = [r for r in rows if r["status"] in ("tp", "sl")]
    wins = [r for r in closed if r["status"] == "tp"]
    total_pnl = sum(float(r["pnl_usd"]) for r in closed if r["pnl_usd"])
    win_rate = 100 * len(wins) / len(closed) if closed else 0.0

    balance_chart = []
    for r in sorted(closed, key=lambda x: int(x["closed_at"] or 0)):
        if r["balance_after"] and r["closed_at"]:
            dt = datetime.fromtimestamp(int(r["closed_at"]), timezone.utc)
            balance_chart.append({
                "label": dt.strftime("%d %b %H:%M"),
                "balance": float(r["balance_after"]),
            })

    return jsonify({
        "balance": state.get("balance", 100.0),
        "total_closed": len(closed),
        "wins": len(wins),
        "losses": len(closed) - len(wins),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "open_trades": len([r for r in rows if r["status"] == "open"]),
        "balance_chart": balance_chart,
    })


# ---------------------------------------------------------------------------
# Single-page dashboard HTML
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>GoldEye Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js" integrity="sha384-e6nUZLBkQ86NJ6TVVKAeSaK8jWa3NhkYWZFomE39AvDbQWeie9PlQqM3pmYW5d1g" crossorigin="anonymous"></script>
<style>
  :root {
    --bg: #0f1117;
    --card: #1a1d27;
    --border: #2a2d3a;
    --gold: #f5c842;
    --green: #26a269;
    --red: #c0392b;
    --text: #e2e8f0;
    --muted: #8892a4;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 20px; }
  h1 { color: var(--gold); font-size: 1.4rem; margin-bottom: 4px; }
  .subtitle { color: var(--muted); font-size: 0.8rem; margin-bottom: 24px; }
  .grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-bottom: 20px; }
  .grid2 { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; margin-bottom: 20px; }
  @media (max-width: 700px) { .grid3, .grid2 { grid-template-columns: 1fr; } }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
  .card-label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: 8px; }
  .card-value { font-size: 1.9rem; font-weight: 700; }
  .card-sub { font-size: 0.78rem; color: var(--muted); margin-top: 4px; }
  .gold { color: var(--gold); }
  .green { color: var(--green); }
  .red { color: var(--red); }
  .chart-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px; margin-bottom: 20px; }
  .chart-title { font-size: 0.85rem; color: var(--muted); margin-bottom: 14px; }
  canvas { max-height: 200px; }
  .open-signal { border-left: 3px solid var(--gold); }
  .no-signal { border-left: 3px solid var(--border); }
  .signal-dir { font-size: 1.1rem; font-weight: 700; margin-bottom: 10px; }
  .signal-row { display: flex; justify-content: space-between; font-size: 0.82rem; padding: 4px 0; border-bottom: 1px solid var(--border); }
  .signal-row:last-child { border-bottom: none; }
  .signal-key { color: var(--muted); }
  .info-row { font-size: 0.82rem; padding: 5px 0; border-bottom: 1px solid var(--border); display: flex; gap: 10px; }
  .info-row:last-child { border-bottom: none; }
  .info-label { color: var(--muted); min-width: 100px; }
  table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
  th { color: var(--muted); text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border); font-weight: 500; font-size: 0.72rem; text-transform: uppercase; }
  td { padding: 8px 10px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; }
  .badge-tp { background: rgba(38,162,105,.2); color: var(--green); }
  .badge-sl { background: rgba(192,57,43,.2); color: var(--red); }
  .badge-open { background: rgba(245,200,66,.15); color: var(--gold); }
  .badge-expired { background: rgba(136,146,164,.15); color: var(--muted); }
  .refresh-note { font-size: 0.72rem; color: var(--muted); text-align: right; margin-top: 20px; }
  #last-refresh { color: var(--gold); }
</style>
</head>
<body>

<h1>⚡ GoldEye</h1>
<div class="subtitle">XAU/USD signal monitor &mdash; refreshes every 60 seconds</div>

<div class="grid3">
  <div class="card">
    <div class="card-label">Balance</div>
    <div class="card-value gold" id="balance">—</div>
    <div class="card-sub" id="pnl-sub">—</div>
  </div>
  <div class="card">
    <div class="card-label">Win Rate</div>
    <div class="card-value" id="win-rate">—</div>
    <div class="card-sub" id="wr-sub">—</div>
  </div>
  <div class="card">
    <div class="card-label">Closed Trades</div>
    <div class="card-value" id="total-closed">—</div>
    <div class="card-sub" id="wl-sub">—</div>
  </div>
</div>

<div class="chart-card">
  <div class="chart-title">Balance over time (closed trades)</div>
  <canvas id="balanceChart"></canvas>
  <div style="color:var(--muted);font-size:0.75rem;margin-top:10px;text-align:center" id="no-chart-msg"></div>
</div>

<div class="grid2">
  <div class="card" id="signal-card">
    <div class="card-label">Current Signal</div>
    <div id="signal-body" style="color:var(--muted);font-size:0.85rem">Loading…</div>
  </div>
  <div class="card">
    <div class="card-label">Bot Status</div>
    <div id="status-body" style="font-size:0.82rem">Loading…</div>
  </div>
</div>

<div class="card">
  <div class="card-label" style="margin-bottom:14px">Signal History (last 20)</div>
  <div style="overflow-x:auto">
    <table id="history-table">
      <thead><tr>
        <th>Date</th><th>Tier</th><th>Dir</th><th>Entry</th>
        <th>SL</th><th>TP</th><th>Score</th><th>Result</th><th>P&amp;L</th>
      </tr></thead>
      <tbody id="history-body"><tr><td colspan="9" style="color:var(--muted);text-align:center">Loading…</td></tr></tbody>
    </table>
  </div>
</div>

<div class="refresh-note">Last refreshed: <span id="last-refresh">—</span></div>

<script>
let balanceChart = null;

function fmt(n, dec=2) {
  return n == null || n === "" ? "—" : parseFloat(n).toFixed(dec);
}

function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("en-GB", {
    day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit", timeZone:"UTC"
  }) + " UTC";
}

async function refresh() {
  const [stateRes, statsRes, sigsRes] = await Promise.all([
    fetch("/api/state").then(r=>r.json()),
    fetch("/api/stats").then(r=>r.json()),
    fetch("/api/signals").then(r=>r.json()),
  ]);

  // --- Stat cards ---
  const pnl = (statsRes.balance - 100).toFixed(2);
  const pnlSign = pnl >= 0 ? "+" : "";
  document.getElementById("balance").textContent = "$" + fmt(statsRes.balance);
  document.getElementById("pnl-sub").innerHTML =
    `<span class="${pnl>=0?'green':'red'}">${pnlSign}${pnl} vs $100 start</span>`;

  const wr = statsRes.win_rate;
  document.getElementById("win-rate").textContent = statsRes.total_closed > 0 ? wr + "%" : "—";
  document.getElementById("win-rate").className = "card-value " + (wr>=50?"green":wr>0?"red":"");
  document.getElementById("wr-sub").textContent = statsRes.total_closed > 0
    ? `${statsRes.wins}W / ${statsRes.losses}L` : "No closed trades yet";

  document.getElementById("total-closed").textContent = statsRes.total_closed;
  document.getElementById("wl-sub").textContent = statsRes.open_trades > 0
    ? `${statsRes.open_trades} open` : "None open";

  // --- Balance chart ---
  const pts = statsRes.balance_chart || [];
  const noChartMsg = document.getElementById("no-chart-msg");
  if (pts.length < 2) {
    noChartMsg.textContent = pts.length === 0
      ? "No closed trades yet — chart will appear after first trade closes"
      : "Need at least 2 closed trades for the chart";
    document.getElementById("balanceChart").style.display = "none";
  } else {
    noChartMsg.textContent = "";
    document.getElementById("balanceChart").style.display = "";
    const labels = pts.map(p=>p.label);
    const values = pts.map(p=>p.balance);
    if (balanceChart) {
      balanceChart.data.labels = labels;
      balanceChart.data.datasets[0].data = values;
      balanceChart.update();
    } else {
      balanceChart = new Chart(document.getElementById("balanceChart"), {
        type: "line",
        data: {
          labels,
          datasets: [{
            data: values,
            borderColor: "#f5c842",
            backgroundColor: "rgba(245,200,66,.08)",
            tension: 0.3,
            pointRadius: 4,
            pointBackgroundColor: values.map((v,i)=>
              i===0 ? "#f5c842" : v>=values[i-1] ? "#26a269" : "#c0392b"),
            fill: true,
          }]
        },
        options: {
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { color:"#8892a4", font:{size:10} }, grid:{color:"#2a2d3a"} },
            y: { ticks: { color:"#8892a4", callback: v=>"$"+v.toFixed(0) }, grid:{color:"#2a2d3a"} },
          }
        }
      });
    }
  }

  // --- Open signal ---
  const sig = stateRes.open_signal;
  const card = document.getElementById("signal-card");
  const body = document.getElementById("signal-body");
  if (sig) {
    card.className = "card open-signal";
    const dirClass = sig.direction === "BUY" ? "green" : "red";
    body.innerHTML = `
      <div class="signal-dir ${dirClass}">${sig.direction} ${sig.tier}</div>
      <div class="signal-row"><span class="signal-key">Entry</span><span>$${fmt(sig.entry)}</span></div>
      <div class="signal-row"><span class="signal-key">Stop Loss</span><span class="red">$${fmt(sig.sl)}</span></div>
      <div class="signal-row"><span class="signal-key">Take Profit</span><span class="green">$${fmt(sig.tp)}</span></div>
      <div class="signal-row"><span class="signal-key">Lot / Risk</span><span>${fmt(sig.lot,2)} lot · $${fmt(sig.risk_usd,2)}</span></div>
      <div class="signal-row"><span class="signal-key">Score</span><span>${sig.score}/7</span></div>
      <div class="signal-row"><span class="signal-key">Since</span><span>${fmtDate(sig.created_ts)}</span></div>
    `;
  } else {
    card.className = "card no-signal";
    const reason = stateRes.last_no_signal || "Watching for a setup…";
    body.innerHTML = `<div style="color:var(--muted)">No signal open</div>
      <div style="margin-top:10px;font-size:0.78rem;color:#6b7280">${reason}</div>`;
  }

  // --- Status panel ---
  const senti = stateRes.last_sentiment || "—";
  const errors = (stateRes.errors || []).slice(-3).reverse();
  const errorHtml = errors.length
    ? errors.map(e=>`<div style="color:var(--red);font-size:0.75rem;margin-top:4px">${e}</div>`).join("")
    : "";
  document.getElementById("status-body").innerHTML = `
    <div class="info-row"><span class="info-label">Last scan</span><span>${stateRes.last_scan_human||"—"}</span></div>
    <div class="info-row"><span class="info-label">Sentiment</span><span>${senti}</span></div>
    ${(stateRes.news_skips||[]).slice(-1).map(s=>
      `<div class="info-row"><span class="info-label">Last skip</span><span style="color:var(--muted)">${s}</span></div>`
    ).join("")}
    ${errorHtml}
  `;

  // --- Signal history table ---
  const rows = [...sigsRes].reverse().slice(0, 20);
  const tbody = document.getElementById("history-body");
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="color:var(--muted);text-align:center;padding:20px">No signals recorded yet</td></tr>';
  } else {
    tbody.innerHTML = rows.map(r => {
      const badgeClass = {tp:"badge-tp",sl:"badge-sl",open:"badge-open",expired:"badge-expired"}[r.status]||"";
      const pnlVal = r.pnl_usd ? parseFloat(r.pnl_usd) : null;
      const pnlHtml = pnlVal != null
        ? `<span class="${pnlVal>=0?'green':'red'}">${pnlVal>=0?"+":""}${pnlVal.toFixed(2)}</span>`
        : "—";
      return `<tr>
        <td>${fmtDate(r.timestamp)}</td>
        <td><span class="gold">${r.tier}</span></td>
        <td><span class="${r.direction==="BUY"?"green":"red"}">${r.direction}</span></td>
        <td>$${fmt(r.entry)}</td>
        <td>$${fmt(r.sl)}</td>
        <td>$${fmt(r.tp)}</td>
        <td>${r.score}/7</td>
        <td><span class="badge ${badgeClass}">${r.status.toUpperCase()}</span></td>
        <td>${pnlHtml}</td>
      </tr>`;
    }).join("");
  }

  document.getElementById("last-refresh").textContent = new Date().toLocaleTimeString();
}

refresh().catch(console.error);
setInterval(() => refresh().catch(console.error), 60000);
</script>
</body>
</html>"""

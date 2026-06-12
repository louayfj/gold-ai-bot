"""GoldEye web dashboard — served from the Fly.io machine.

Exposes:
  GET /            — HTML dashboard (auto-refreshes every 60s)
  GET /api/state   — current bot state (balance, open signal, last scan)
  GET /api/signals — all signals from signals.csv as JSON
  GET /api/stats   — summary stats + analytics
"""

from datetime import datetime, timezone

from flask import Flask, jsonify

from goldeye import storage

app = Flask(__name__)

_SESSION_ORDER = ["London", "Overlap", "New York", "Off-hours"]


def _session_name(ts_str: str) -> str:
    hour = datetime.fromtimestamp(int(ts_str), timezone.utc).hour
    if 7 <= hour < 12:
        return "London"
    if 12 <= hour < 17:
        return "Overlap"
    if 17 <= hour < 21:
        return "New York"
    return "Off-hours"


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
    losses = [r for r in closed if r["status"] == "sl"]
    total_pnl = sum(float(r["pnl_usd"]) for r in closed if r["pnl_usd"])
    win_rate = 100 * len(wins) / len(closed) if closed else 0.0

    sorted_closed = sorted(closed, key=lambda x: int(x["closed_at"] or 0))

    # Balance chart (equity curve)
    balance_chart = []
    for r in sorted_closed:
        if r["balance_after"] and r["closed_at"]:
            dt = datetime.fromtimestamp(int(r["closed_at"]), timezone.utc)
            balance_chart.append({
                "label": dt.strftime("%d %b %H:%M"),
                "balance": float(r["balance_after"]),
            })

    # Profit factor
    gross_wins = sum(float(r["pnl_usd"]) for r in wins if r["pnl_usd"])
    gross_losses = abs(sum(float(r["pnl_usd"]) for r in losses if r["pnl_usd"]))
    profit_factor = round(gross_wins / gross_losses, 2) if gross_losses > 0 else None

    # Max drawdown (peak-to-trough as %)
    peak = 100.0
    max_dd = 0.0
    for r in sorted_closed:
        if r["balance_after"]:
            bal = float(r["balance_after"])
            peak = max(peak, bal)
            dd = (peak - bal) / peak * 100
            max_dd = max(max_dd, dd)

    # Streak (consecutive wins or losses from most recent)
    streak, streak_type = 0, None
    for r in reversed(sorted_closed):
        s = r["status"]
        if streak_type is None:
            streak_type = s
        if s == streak_type:
            streak += 1
        else:
            break
    if streak_type == "tp":
        streak_type = "win"
    elif streak_type == "sl":
        streak_type = "loss"
    else:
        streak_type = None

    # Average trade duration in hours
    durations = [
        (int(r["closed_at"]) - int(r["timestamp"])) / 3600
        for r in closed if r["timestamp"] and r["closed_at"]
    ]
    avg_duration_h = round(sum(durations) / len(durations), 1) if durations else None

    # Win rate by score
    score_map: dict = {}
    for r in closed:
        s = str(r["score"])
        entry = score_map.setdefault(s, {"wins": 0, "total": 0})
        entry["total"] += 1
        if r["status"] == "tp":
            entry["wins"] += 1
    score_breakdown = [
        {"score": k, "total": v["total"], "wins": v["wins"],
         "win_rate": round(100 * v["wins"] / v["total"], 1)}
        for k, v in sorted(score_map.items(), key=lambda x: int(x[0]))
    ]

    # Win rate by session
    session_map: dict = {}
    for r in closed:
        sess = _session_name(r["timestamp"])
        entry = session_map.setdefault(sess, {"wins": 0, "total": 0})
        entry["total"] += 1
        if r["status"] == "tp":
            entry["wins"] += 1
    session_breakdown = [
        {"session": k, "total": session_map[k]["total"],
         "wins": session_map[k]["wins"],
         "win_rate": round(100 * session_map[k]["wins"] / session_map[k]["total"], 1)}
        for k in _SESSION_ORDER if k in session_map
    ]

    return jsonify({
        "balance": state.get("balance", 100.0),
        "total_closed": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl": round(total_pnl, 2),
        "open_trades": len([r for r in rows if r["status"] == "open"]),
        "balance_chart": balance_chart,
        "profit_factor": profit_factor,
        "max_drawdown_pct": round(max_dd, 2),
        "streak": streak,
        "streak_type": streak_type,
        "avg_duration_h": avg_duration_h,
        "score_breakdown": score_breakdown,
        "session_breakdown": session_breakdown,
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
  --bg: #0f1117; --card: #1a1d27; --border: #2a2d3a;
  --gold: #f5c842; --green: #26a269; --red: #c0392b;
  --orange: #e67e22; --text: #e2e8f0; --muted: #8892a4;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; padding: 16px; max-width: 1200px; margin: 0 auto; }
h1 { color: var(--gold); font-size: 1.3rem; }
.subtitle { color: var(--muted); font-size: 0.75rem; margin-bottom: 20px; }
.section-label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin: 20px 0 10px; }

/* Grids */
.grid6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 0; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.grid7 { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; }
@media (max-width: 800px) {
  .grid6 { grid-template-columns: repeat(3, 1fr); }
  .grid7 { grid-template-columns: repeat(4, 1fr); }
  .grid2 { grid-template-columns: 1fr; }
}
@media (max-width: 500px) {
  .grid6 { grid-template-columns: repeat(2, 1fr); }
  .grid7 { grid-template-columns: repeat(2, 1fr); }
}

/* Cards */
.card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
.card-label { font-size: 0.68rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: 6px; }
.card-value { font-size: 1.6rem; font-weight: 700; }
.card-sub { font-size: 0.74rem; color: var(--muted); margin-top: 4px; }

/* Factor gauge tiles */
.factor-tile { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 8px; text-align: center; }
.factor-name { font-size: 0.68rem; text-transform: uppercase; letter-spacing: .06em; color: var(--muted); margin-bottom: 6px; }
.factor-arrow { font-size: 1.4rem; line-height: 1; }
.factor-label { font-size: 0.65rem; color: var(--muted); margin-top: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.factor-tile.buy { border-color: rgba(38,162,105,.4); background: rgba(38,162,105,.07); }
.factor-tile.sell { border-color: rgba(192,57,43,.4); background: rgba(192,57,43,.07); }

/* Chart */
.chart-card { background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
canvas { max-height: 180px; }

/* Signal card */
.open-signal { border-left: 3px solid var(--gold); }
.no-signal { border-left: 3px solid var(--border); }
.signal-dir { font-size: 1rem; font-weight: 700; margin-bottom: 10px; }
.signal-row { display: flex; justify-content: space-between; font-size: 0.8rem; padding: 3px 0; border-bottom: 1px solid var(--border); }
.signal-row:last-child { border-bottom: none; }
.signal-key { color: var(--muted); }

/* Activity log */
.activity-entry { padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.78rem; display: flex; gap: 8px; align-items: flex-start; }
.activity-entry:last-child { border-bottom: none; }
.activity-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 4px; }
.act-signal { background: var(--gold); }
.act-skipped { background: var(--orange); }
.act-closed_tp { background: var(--green); }
.act-closed_sl { background: var(--red); }
.act-no_setup, .act-wide_stop, .act-closed_expired { background: var(--muted); }
.activity-time { color: var(--muted); font-size: 0.7rem; white-space: nowrap; }
.activity-body { flex: 1; }

/* Analytics tables */
.analytics-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
.analytics-table th { color: var(--muted); text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); font-weight: 500; font-size: 0.68rem; text-transform: uppercase; }
.analytics-table td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
.analytics-table tr:last-child td { border-bottom: none; }
.wr-bar { height: 4px; border-radius: 2px; background: var(--border); margin-top: 3px; }
.wr-fill { height: 100%; border-radius: 2px; }

/* Signal history table */
table.history { width: 100%; border-collapse: collapse; font-size: 0.78rem; }
table.history th { color: var(--muted); text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border); font-weight: 500; font-size: 0.68rem; text-transform: uppercase; }
table.history td { padding: 7px 8px; border-bottom: 1px solid var(--border); }
table.history tr:last-child td { border-bottom: none; }
.badge { display: inline-block; padding: 1px 7px; border-radius: 4px; font-size: 0.68rem; font-weight: 600; }
.badge-tp { background: rgba(38,162,105,.2); color: var(--green); }
.badge-sl { background: rgba(192,57,43,.2); color: var(--red); }
.badge-open { background: rgba(245,200,66,.15); color: var(--gold); }
.badge-expired { background: rgba(136,146,164,.15); color: var(--muted); }

/* Colours */
.gold { color: var(--gold); }
.green { color: var(--green); }
.red { color: var(--red); }
.muted { color: var(--muted); }

.refresh-note { font-size: 0.7rem; color: var(--muted); text-align: right; margin-top: 16px; }
</style>
</head>
<body>

<h1>⚡ GoldEye</h1>
<div class="subtitle">XAU/USD signal monitor &mdash; auto-refreshes every 60 s &mdash; last update: <span id="last-refresh">—</span></div>

<!-- Stat cards -->
<div class="section-label">Performance</div>
<div class="grid6">
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
    <div class="card-label">Profit Factor</div>
    <div class="card-value" id="profit-factor">—</div>
    <div class="card-sub">wins ÷ losses $</div>
  </div>
  <div class="card">
    <div class="card-label">Max Drawdown</div>
    <div class="card-value" id="max-dd">—</div>
    <div class="card-sub">worst peak→trough</div>
  </div>
  <div class="card">
    <div class="card-label">Streak</div>
    <div class="card-value" id="streak">—</div>
    <div class="card-sub" id="streak-sub">—</div>
  </div>
  <div class="card">
    <div class="card-label">Avg Duration</div>
    <div class="card-value" id="avg-dur">—</div>
    <div class="card-sub">per trade</div>
  </div>
</div>

<!-- Balance chart -->
<div class="section-label">Equity Curve</div>
<div class="chart-card">
  <canvas id="balanceChart"></canvas>
  <div style="color:var(--muted);font-size:0.74rem;text-align:center;margin-top:8px" id="no-chart-msg"></div>
</div>

<!-- Factor vote gauges -->
<div class="section-label">Current Market Factors <span style="color:var(--muted);font-size:0.68rem;font-weight:400">(▲ = bullish vote · ▼ = bearish · — = no vote)</span></div>
<div class="grid7" id="factor-gauges">
  <div class="factor-tile muted" style="grid-column:1/-1;text-align:center;padding:12px;font-size:0.8rem">Loading factor votes…</div>
</div>

<!-- Signal + Activity -->
<div class="section-label">Live Status</div>
<div class="grid2">
  <div class="card" id="signal-card">
    <div class="card-label">Current Signal</div>
    <div id="signal-body" style="color:var(--muted);font-size:0.84rem">Loading…</div>
  </div>
  <div class="card" style="overflow:hidden">
    <div class="card-label" style="margin-bottom:10px">Activity Log <span style="color:var(--muted);font-weight:400">(last 10 scans)</span></div>
    <div id="activity-log" style="max-height:240px;overflow-y:auto">Loading…</div>
  </div>
</div>

<!-- Analytics -->
<div class="section-label">Analytics</div>
<div class="grid2">
  <div class="card">
    <div class="card-label" style="margin-bottom:10px">Win Rate by Score</div>
    <table class="analytics-table" id="score-table">
      <thead><tr><th>Score</th><th>Trades</th><th>Win Rate</th></tr></thead>
      <tbody id="score-body"><tr><td colspan="3" class="muted">No data yet</td></tr></tbody>
    </table>
  </div>
  <div class="card">
    <div class="card-label" style="margin-bottom:10px">Win Rate by Session</div>
    <table class="analytics-table" id="session-table">
      <thead><tr><th>Session</th><th>Trades</th><th>Win Rate</th></tr></thead>
      <tbody id="session-body"><tr><td colspan="3" class="muted">No data yet</td></tr></tbody>
    </table>
  </div>
</div>

<!-- Signal history -->
<div class="section-label">Signal History <span style="color:var(--muted);font-size:0.68rem;font-weight:400">(last 20)</span></div>
<div class="card">
  <div style="overflow-x:auto">
    <table class="history">
      <thead><tr>
        <th>Date (UTC)</th><th>Tier</th><th>Dir</th><th>Entry</th>
        <th>SL</th><th>TP</th><th>Score</th><th>Result</th><th>P&amp;L</th>
      </tr></thead>
      <tbody id="history-body"><tr><td colspan="9" style="color:var(--muted);text-align:center">Loading…</td></tr></tbody>
    </table>
  </div>
</div>

<div class="refresh-note">Prices and signals are informational only — not financial advice.</div>

<script>
let balanceChart = null;

const EVT_LABEL = {
  signal: "Signal sent",
  skipped_calendar: "Skipped — news event",
  skipped_sentiment: "Skipped — sentiment",
  skipped_ml: "Skipped — ML too low",
  no_setup: "No setup",
  wide_stop: "Wide stop (risk too large)",
  closed_tp: "Closed TP ✓",
  closed_sl: "Closed SL ✗",
  closed_expired: "Expired",
};

function fmt(n, dec=2) {
  return n == null || n === "" ? "—" : parseFloat(n).toFixed(dec);
}

function fmtDate(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("en-GB", {
    day:"2-digit", month:"short", hour:"2-digit", minute:"2-digit", timeZone:"UTC"
  }) + " UTC";
}

function fmtDur(h) {
  if (h == null) return "—";
  const hrs = Math.floor(h);
  const mins = Math.round((h - hrs) * 60);
  return hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
}

function wrColor(wr) {
  if (wr >= 55) return "var(--green)";
  if (wr >= 45) return "var(--gold)";
  return "var(--red)";
}

async function refresh() {
  const [stateRes, statsRes, sigsRes] = await Promise.all([
    fetch("/api/state").then(r=>r.json()),
    fetch("/api/stats").then(r=>r.json()),
    fetch("/api/signals").then(r=>r.json()),
  ]);

  // --- Stat cards ---
  const pnl = (statsRes.balance - 100).toFixed(2);
  const sign = pnl >= 0 ? "+" : "";
  document.getElementById("balance").textContent = "$" + fmt(statsRes.balance);
  document.getElementById("pnl-sub").innerHTML =
    `<span class="${pnl>=0?'green':'red'}">${sign}${pnl} vs $100 start</span>`;

  const wr = statsRes.win_rate;
  document.getElementById("win-rate").textContent = statsRes.total_closed > 0 ? wr + "%" : "—";
  document.getElementById("win-rate").style.color = statsRes.total_closed > 0 ? wrColor(wr) : "";
  document.getElementById("wr-sub").textContent = statsRes.total_closed > 0
    ? `${statsRes.wins}W / ${statsRes.losses}L · ${statsRes.total_closed} trades` : "No closed trades yet";

  const pf = statsRes.profit_factor;
  const pfEl = document.getElementById("profit-factor");
  pfEl.textContent = pf != null ? pf.toFixed(2) : "—";
  pfEl.style.color = pf == null ? "" : pf >= 1.5 ? "var(--green)" : pf >= 1.0 ? "var(--gold)" : "var(--red)";

  const dd = statsRes.max_drawdown_pct;
  const ddEl = document.getElementById("max-dd");
  ddEl.textContent = dd != null ? dd.toFixed(1) + "%" : "—";
  ddEl.style.color = dd == null ? "" : dd < 5 ? "var(--green)" : dd < 10 ? "var(--gold)" : "var(--red)";

  const strk = statsRes.streak;
  const strkEl = document.getElementById("streak");
  if (!strk) {
    strkEl.textContent = "—";
    document.getElementById("streak-sub").textContent = "—";
  } else {
    strkEl.textContent = strk + (statsRes.streak_type === "win" ? "W" : "L");
    strkEl.style.color = statsRes.streak_type === "win" ? "var(--green)" : "var(--red)";
    document.getElementById("streak-sub").textContent =
      statsRes.streak_type === "win" ? "wins in a row" : "losses in a row";
  }
  document.getElementById("avg-dur").textContent = fmtDur(statsRes.avg_duration_h);

  // --- Balance chart ---
  const pts = statsRes.balance_chart || [];
  const noMsg = document.getElementById("no-chart-msg");
  if (pts.length < 2) {
    noMsg.textContent = pts.length === 0
      ? "Chart will appear after the first trade closes"
      : "Need at least 2 closed trades for the chart";
    document.getElementById("balanceChart").style.display = "none";
  } else {
    noMsg.textContent = "";
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
            pointRadius: 5,
            pointBackgroundColor: values.map((v,i)=>
              i===0 ? "#f5c842" : v >= values[i-1] ? "#26a269" : "#c0392b"),
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

  // --- Factor vote gauges ---
  const fvotes = stateRes.last_factor_votes || [];
  const gaugesEl = document.getElementById("factor-gauges");
  if (fvotes.length === 0) {
    gaugesEl.innerHTML = '<div class="factor-tile muted" style="grid-column:1/-1;text-align:center;padding:12px;font-size:0.8rem">No factor data yet — will appear after next scan</div>';
  } else {
    gaugesEl.innerHTML = fvotes.map(f => {
      const cls = f.buy ? "buy" : f.sell ? "sell" : "";
      const arrow = f.buy ? "▲" : f.sell ? "▼" : "—";
      const arrowColor = f.buy ? "var(--green)" : f.sell ? "var(--red)" : "var(--muted)";
      return `<div class="factor-tile ${cls}">
        <div class="factor-name">${f.name}</div>
        <div class="factor-arrow" style="color:${arrowColor}">${arrow}</div>
        <div class="factor-label" title="${f.label}">${f.label}</div>
      </div>`;
    }).join("");
  }

  // --- Open signal ---
  const sig = stateRes.open_signal;
  const card = document.getElementById("signal-card");
  const body = document.getElementById("signal-body");
  if (sig) {
    card.className = "card open-signal";
    const dirCls = sig.direction === "BUY" ? "green" : "red";
    body.innerHTML = `
      <div class="signal-dir ${dirCls}">${sig.direction} ${sig.tier}</div>
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
    const senti = stateRes.last_sentiment || "";
    body.innerHTML = `
      <div style="color:var(--muted)">No signal open</div>
      ${senti ? `<div style="margin-top:6px;font-size:0.75rem;color:var(--muted)">Sentiment: ${senti}</div>` : ""}
      <div style="margin-top:8px;font-size:0.75rem;color:#6b7280">${reason}</div>
    `;
  }

  // --- Activity log ---
  const log = (stateRes.activity_log || []).slice().reverse().slice(0, 10);
  const logEl = document.getElementById("activity-log");
  if (log.length === 0) {
    logEl.innerHTML = '<div style="color:var(--muted);font-size:0.8rem">No activity yet — will fill in as scans run</div>';
  } else {
    logEl.innerHTML = log.map(e => {
      const dotCls = e.event === "signal" ? "act-signal"
        : e.event.startsWith("skipped") ? "act-skipped"
        : `act-${e.event}`;
      const label = EVT_LABEL[e.event] || e.event;
      const dir = e.direction ? `<span class="${e.direction==="BUY"?"green":"red"}">${e.direction}</span> ` : "";
      const score = e.score ? `${e.score}/7 · ` : "";
      return `<div class="activity-entry">
        <div class="activity-dot ${dotCls}"></div>
        <div class="activity-body">
          <span style="font-weight:600">${label}</span>
          ${e.detail ? `<span class="muted"> — ${e.detail}</span>` : ""}
          <div class="activity-time">${e.time || ""}</div>
        </div>
      </div>`;
    }).join("");
  }

  // --- Analytics tables ---
  const scoreRows = statsRes.score_breakdown || [];
  document.getElementById("score-body").innerHTML = scoreRows.length === 0
    ? '<tr><td colspan="3" class="muted" style="text-align:center">No closed trades yet</td></tr>'
    : scoreRows.map(r => {
        const color = wrColor(r.win_rate);
        return `<tr>
          <td><span class="gold">${r.score}/7</span></td>
          <td>${r.total}</td>
          <td>
            <span style="color:${color}">${r.win_rate}%</span>
            <div class="wr-bar"><div class="wr-fill" style="width:${r.win_rate}%;background:${color}"></div></div>
          </td>
        </tr>`;
      }).join("");

  const sessRows = statsRes.session_breakdown || [];
  document.getElementById("session-body").innerHTML = sessRows.length === 0
    ? '<tr><td colspan="3" class="muted" style="text-align:center">No closed trades yet</td></tr>'
    : sessRows.map(r => {
        const color = wrColor(r.win_rate);
        return `<tr>
          <td>${r.session}</td>
          <td>${r.total}</td>
          <td>
            <span style="color:${color}">${r.win_rate}%</span>
            <div class="wr-bar"><div class="wr-fill" style="width:${r.win_rate}%;background:${color}"></div></div>
          </td>
        </tr>`;
      }).join("");

  // --- Signal history table ---
  const histRows = [...sigsRes].reverse().slice(0, 20);
  const tbody = document.getElementById("history-body");
  if (histRows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="9" style="color:var(--muted);text-align:center;padding:20px">No signals recorded yet</td></tr>';
  } else {
    tbody.innerHTML = histRows.map(r => {
      const badgeCls = {tp:"badge-tp",sl:"badge-sl",open:"badge-open",expired:"badge-expired"}[r.status] || "";
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
        <td><span class="badge ${badgeCls}">${r.status.toUpperCase()}</span></td>
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

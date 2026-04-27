"""Live web dashboard for the Polymarket trading bot.

Reads `.bot_state.json` (written by the strategy each cycle) and serves a
real-time view of trades, win rate, PnL, and open positions.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string

from .config import Config


STATE_FILE = Path(".bot_state.json")


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Polymarket Bot — Live Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  :root {
    --bg: #0b0d10;
    --panel: #14181f;
    --panel-2: #1a1f28;
    --border: #232a36;
    --text: #e6edf3;
    --muted: #8b9aae;
    --accent: #4ade80;
    --danger: #f87171;
    --warn: #fbbf24;
    --brand: #818cf8;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
  }
  .wrap { max-width: 1200px; margin: 0 auto; padding: 24px; }
  header { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
  h1 { font-size: 22px; margin: 0; font-weight: 600; }
  .pill {
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 10px; border-radius: 999px;
    font-size: 12px; font-weight: 600; letter-spacing: .04em;
    background: var(--panel-2); border: 1px solid var(--border);
  }
  .pill.live { color: var(--danger); border-color: rgba(248,113,113,.4); }
  .pill.paper { color: var(--brand); border-color: rgba(129,140,248,.4); }
  .meta { color: var(--muted); font-size: 13px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 24px; }
  .card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 18px;
  }
  .card .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .06em; margin-bottom: 6px; }
  .card .value { font-size: 26px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .pos { color: var(--accent); }
  .neg { color: var(--danger); }
  .neutral { color: var(--text); }
  .section { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; margin-bottom: 16px; overflow: hidden; }
  .section h2 { font-size: 14px; font-weight: 600; margin: 0; padding: 14px 18px; border-bottom: 1px solid var(--border); color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 10px 18px; border-bottom: 1px solid var(--border); }
  th { color: var(--muted); font-weight: 500; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
  tr:last-child td { border-bottom: none; }
  td.right, th.right { text-align: right; }
  .q { max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .badge.tp { background: rgba(74,222,128,.12); color: var(--accent); }
  .badge.sl { background: rgba(248,113,113,.12); color: var(--danger); }
  .empty { padding: 28px 18px; text-align: center; color: var(--muted); font-size: 13px; }
  .footer { color: var(--muted); font-size: 12px; text-align: center; margin-top: 32px; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--accent); animation: pulse 1.6s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Polymarket Bot <span id="mode-pill" class="pill paper">PAPER</span></h1>
      <div class="meta"><span class="dot"></span> Live data — refreshes every 5s · Last update: <span id="last-update">—</span></div>
    </div>
    <div class="meta">Strategy: cheap-YES scanner</div>
  </header>

  <div class="grid">
    <div class="card"><div class="label">Trades opened</div><div class="value neutral" id="opened">0</div></div>
    <div class="card"><div class="label">Trades closed</div><div class="value neutral" id="closed">0</div></div>
    <div class="card"><div class="label">Win rate</div><div class="value neutral" id="winrate">—</div></div>
    <div class="card"><div class="label">Realized PnL</div><div class="value neutral" id="realized">$0.00</div></div>
    <div class="card"><div class="label">Unrealized PnL</div><div class="value neutral" id="unrealized">$0.00</div></div>
    <div class="card"><div class="label">Open positions</div><div class="value neutral" id="open-count">0</div></div>
  </div>

  <div class="section">
    <h2>Cumulative PnL</h2>
    <div id="chart-wrap" style="padding: 18px; height: 280px; position: relative;">
      <canvas id="pnl-chart"></canvas>
      <div id="chart-empty" class="empty" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;">Waiting for first cycle…</div>
    </div>
  </div>

  <div class="section">
    <h2>Open positions</h2>
    <div id="open-table"></div>
  </div>

  <div class="section">
    <h2>Recent closed trades</h2>
    <div id="closed-table"></div>
  </div>

  <div class="footer">Polymarket Bot dashboard · auto-refresh enabled</div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
const fmt = (n, d = 2) => (n >= 0 ? "+" : "-") + "$" + Math.abs(n).toFixed(d);
const fmtPlain = (n, d = 2) => "$" + Number(n).toFixed(d);
const fmtPct = (n) => (Number(n) * 100).toFixed(1) + "%";

function pnlClass(v) { return v > 0 ? "pos" : v < 0 ? "neg" : "neutral"; }

function setText(id, text, klass) {
  const el = document.getElementById(id);
  el.textContent = text;
  if (klass) { el.classList.remove("pos","neg","neutral"); el.classList.add(klass); }
}

function renderOpen(positions) {
  const host = document.getElementById("open-table");
  if (!positions.length) { host.innerHTML = '<div class="empty">No open positions yet.</div>'; return; }
  let html = '<table><thead><tr><th>Market</th><th>Mode</th><th class="right">Size</th><th class="right">Entry</th><th class="right">Mark</th><th class="right">Unrealized PnL</th></tr></thead><tbody>';
  for (const p of positions) {
    const pnl = (p.latest_bid - p.price) * p.size;
    html += `<tr>
      <td class="q" title="${p.question}">${p.question}</td>
      <td>${p.mode}</td>
      <td class="right">${p.size.toFixed(2)}</td>
      <td class="right">${p.price.toFixed(3)}</td>
      <td class="right">${p.latest_bid.toFixed(3)}</td>
      <td class="right ${pnlClass(pnl)}">${fmt(pnl)}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  host.innerHTML = html;
}

function renderClosed(positions) {
  const host = document.getElementById("closed-table");
  if (!positions.length) { host.innerHTML = '<div class="empty">No closed trades yet — exits fire when YES hits 30¢ (take-profit) or 1¢ (stop-loss).</div>'; return; }
  const recent = positions.slice(-25).reverse();
  let html = '<table><thead><tr><th>Market</th><th>Reason</th><th class="right">Entry</th><th class="right">Exit</th><th class="right">PnL</th><th>Closed</th></tr></thead><tbody>';
  for (const p of recent) {
    const badge = p.exit_reason === "TAKE-PROFIT" ? '<span class="badge tp">TP</span>' : '<span class="badge sl">SL</span>';
    html += `<tr>
      <td class="q" title="${p.question}">${p.question}</td>
      <td>${badge}</td>
      <td class="right">${p.price.toFixed(3)}</td>
      <td class="right">${p.exit_price.toFixed(3)}</td>
      <td class="right ${pnlClass(p.realized_pnl_usdc)}">${fmt(p.realized_pnl_usdc)}</td>
      <td>${new Date(p.closed_at).toLocaleTimeString()}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  host.innerHTML = html;
}

let pnlChart = null;
function ensureChart() {
  if (pnlChart) return pnlChart;
  const ctx = document.getElementById("pnl-chart").getContext("2d");
  const grid = "rgba(255,255,255,0.06)";
  const tickColor = "#8b9aae";
  pnlChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Total PnL",
          data: [],
          borderColor: "#818cf8",
          backgroundColor: "rgba(129,140,248,0.18)",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.25,
          fill: true,
        },
        {
          label: "Realized",
          data: [],
          borderColor: "#4ade80",
          borderWidth: 1.5,
          borderDash: [4, 4],
          pointRadius: 0,
          tension: 0.25,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: tickColor, boxWidth: 12, font: { size: 11 } } },
        tooltip: {
          callbacks: {
            label: (c) => c.dataset.label + ": " + (c.parsed.y >= 0 ? "+" : "-") + "$" + Math.abs(c.parsed.y).toFixed(2),
          },
        },
      },
      scales: {
        x: { grid: { color: grid }, ticks: { color: tickColor, maxRotation: 0, autoSkipPadding: 24 } },
        y: { grid: { color: grid }, ticks: { color: tickColor, callback: (v) => "$" + Number(v).toFixed(2) } },
      },
    },
  });
  return pnlChart;
}

function updateChart(history) {
  const empty = document.getElementById("chart-empty");
  if (!history || !history.length) {
    empty.style.display = "flex";
    return;
  }
  empty.style.display = "none";
  const c = ensureChart();
  c.data.labels = history.map((h) => new Date(h.t).toLocaleTimeString());
  c.data.datasets[0].data = history.map((h) => Number(h.total));
  c.data.datasets[1].data = history.map((h) => Number(h.realized));
  c.update("none");
}

async function refresh() {
  try {
    const r = await fetch("api/stats", { cache: "no-store" });
    const d = await r.json();

    const pill = document.getElementById("mode-pill");
    pill.textContent = d.mode.toUpperCase();
    pill.className = "pill " + d.mode;

    setText("opened", d.trades_opened);
    setText("closed", d.trades_closed);
    setText("winrate", d.trades_closed ? fmtPct(d.win_rate) : "—",
            d.trades_closed ? (d.win_rate >= 0.5 ? "pos" : "neg") : "neutral");
    setText("realized", fmt(d.realized_pnl_usdc), pnlClass(d.realized_pnl_usdc));
    setText("unrealized", fmt(d.unrealized_pnl_usdc), pnlClass(d.unrealized_pnl_usdc));
    setText("open-count", d.open_positions.length);
    document.getElementById("last-update").textContent = new Date().toLocaleTimeString();

    renderOpen(d.open_positions);
    renderClosed(d.closed_positions);
    updateChart(d.pnl_history);
  } catch (e) {
    document.getElementById("last-update").textContent = "error";
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


def _read_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {
            "spent_usdc": {"live": 0.0, "paper": 0.0},
            "open_positions": [],
            "closed_positions": [],
        }
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return {"open_positions": [], "closed_positions": []}


def _compute_stats(state: dict[str, Any], mode: str) -> dict[str, Any]:
    open_pos = [p for p in state.get("open_positions", []) if p.get("mode") == mode]
    closed_pos = [p for p in state.get("closed_positions", []) if p.get("mode") == mode]

    realized = round(sum(float(p.get("realized_pnl_usdc", 0.0)) for p in closed_pos), 4)
    unrealized = round(
        sum(
            (float(p.get("latest_bid", p.get("price", 0.0))) - float(p.get("price", 0.0)))
            * float(p.get("size", 0.0))
            for p in open_pos
        ),
        4,
    )
    wins = sum(1 for p in closed_pos if p.get("win"))
    win_rate = (wins / len(closed_pos)) if closed_pos else 0.0

    pnl_history_root = state.get("pnl_history") or {}
    pnl_history = (
        pnl_history_root.get(mode, []) if isinstance(pnl_history_root, dict) else []
    )

    return {
        "mode": mode,
        "trades_opened": len(open_pos) + len(closed_pos),
        "trades_closed": len(closed_pos),
        "trades_open": len(open_pos),
        "wins": wins,
        "losses": len(closed_pos) - wins,
        "win_rate": win_rate,
        "realized_pnl_usdc": realized,
        "unrealized_pnl_usdc": unrealized,
        "open_positions": open_pos,
        "closed_positions": closed_pos,
        "pnl_history": pnl_history,
    }


def make_app(config: Config) -> Flask:
    app = Flask(__name__)

    # Quiet Flask's request logger — keep the bot's own log clean.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    mode = "paper" if config.dry_run else "live"

    @app.route("/")
    def index():  # type: ignore[no-untyped-def]
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/stats")
    def stats():  # type: ignore[no-untyped-def]
        return jsonify(_compute_stats(_read_state(), mode))

    return app


def start_dashboard_in_thread(config: Config, port: int, logger: logging.Logger) -> None:
    app = make_app(config)

    def _run() -> None:
        logger.info("Dashboard listening on port %d", port)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, name="dashboard", daemon=True)
    t.start()

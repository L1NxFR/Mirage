"""Render the simulated TPOT curves as one interactive HTML page.

    python3 src/two-tier-dram-engine/curves_page.py --out PAGE.html [RUN_DIR ...]

Two charts: TPOT against the tier-1/tier-2 bandwidth (tier 1 at 96 GB) and TPOT against tier-1
capacity (tier 2 at 1 TB/s). Each RUN_DIR is a curves.py output (summary.json), one per
synthetic-routing overlap. Each chart shows the two-tier TPOT and AISim's native TPOT of the same
passes (every byte already in tier 1, no tier-2 waits). Default RUN_DIRs:
output/curves and output/curves-overlap0.9.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTEXT = {"262144": "256k", "1048576": "1m"}


def simulated(run_dir: Path) -> tuple[str, dict, str]:
    summary = json.loads((run_dir / "summary.json").read_text())
    out: dict = {"bw": {}, "cap": {}}
    for r in summary["results"]:
        if "error" in r:
            continue
        sweep = r["figure"].split("-")[0]
        x = float(r["l2_bw_tbps"] if sweep == "bw" else r["l1_gb"])
        out[sweep].setdefault(CONTEXT[r["context_tokens"]], []).append(
            {"x": x, "ideal": round(r["sim_ideal_ms"], 2), "obtained": round(r["sim_obtained_ms"], 2),
             "fetch": round(r["sim_fetch_gb_per_step"], 2), "hit": round(r["expert_hit_rate"], 3)})
    for sweep in out.values():
        for series in sweep.values():
            series.sort(key=lambda p: p["x"])
    return f"{summary['expert_overlap']:g}", out, summary["aisim"]


PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>两级 DRAM：TPOT 与带宽、一级容量</title>
<style>
.viz-root {
  color-scheme: light;
  --surface-1: #fcfcfb; --text-primary: #0b0b0b; --text-secondary: #52514e; --text-muted: #77756f;
  --grid: #e6e5e0; --axis: #b9b7b0; --control: #f1f0ec; --control-on: #0b0b0b; --control-on-text: #fcfcfb;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100; --s5: #e87ba4;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #96958c;
    --grid: #2e2d2b; --axis: #55544f; --control: #262624; --control-on: #f0efec; --control-on-text: #1a1a19;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181;
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --surface-1: #1a1a19; --text-primary: #f0efec; --text-secondary: #c3c2b7; --text-muted: #96958c;
  --grid: #2e2d2b; --axis: #55544f; --control: #262624; --control-on: #f0efec; --control-on-text: #1a1a19;
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181;
}
html, body { margin: 0; background: var(--surface-1, #fcfcfb); }
.viz-root { background: var(--surface-1); color: var(--text-primary); font: 14px/1.5 -apple-system, "PingFang SC", "Noto Sans CJK SC", system-ui, sans-serif; padding: 16px 20px 20px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px 20px; align-items: center; margin-bottom: 14px; }
.group { display: flex; align-items: center; gap: 6px; }
.group > span { color: var(--text-secondary); font-size: 13px; }
.seg { display: inline-flex; background: var(--control); border-radius: 8px; padding: 2px; }
.seg button { border: 0; background: transparent; color: var(--text-secondary); font: inherit; font-size: 13px; padding: 3px 10px; border-radius: 6px; cursor: pointer; }
.seg button[aria-pressed="true"] { background: var(--control-on); color: var(--control-on-text); }
.legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin: 0 0 6px; }
.legend button { display: inline-flex; align-items: center; gap: 6px; border: 0; background: none; color: var(--text-primary); font: inherit; font-size: 13px; cursor: pointer; padding: 2px 0; }
.legend button[aria-pressed="false"] { color: var(--text-muted); text-decoration: line-through; }
.legend i { width: 16px; height: 0; border-top: 2px solid; display: inline-block; }
.chart { position: relative; margin: 6px 0 22px; }
.chart h2 { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
.chart p.sub { margin: 0 0 6px; color: var(--text-secondary); font-size: 13px; }
svg { width: 100%; height: auto; display: block; overflow: visible; }
.tick text { fill: var(--text-secondary); font-size: 11px; }
.axis-title { fill: var(--text-secondary); font-size: 12px; }
.tip { position: absolute; pointer-events: none; background: var(--surface-1); color: var(--text-primary); border: 1px solid var(--axis); border-radius: 8px; padding: 6px 10px; font-size: 12px; box-shadow: 0 4px 14px rgba(0,0,0,.12); display: none; white-space: nowrap; z-index: 2; }
.tip b { font-weight: 600; }
.tip .row { display: flex; align-items: center; gap: 6px; }
.tip .row i { width: 10px; height: 0; border-top: 2px solid; }
.tip .row span:last-child { margin-left: auto; padding-left: 12px; font-variant-numeric: tabular-nums; }
table { border-collapse: collapse; font-size: 12px; margin: 4px 0 18px; font-variant-numeric: tabular-nums; }
th, td { border-bottom: 1px solid var(--grid); padding: 3px 10px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { color: var(--text-secondary); font-weight: 500; }
.note { color: var(--text-muted); font-size: 12px; margin-top: 4px; }
</style>
</head>
<body>
<div class="viz-root" id="root">
  <div class="filters">
    <div class="group"><span>上下文</span><div class="seg" data-key="ctx"><button data-v="256k">256K</button><button data-v="1m">1M</button></div></div>
    <div class="group"><span>路由跨步重合度</span><div class="seg" data-key="ov" id="ov"></div></div>
    <div class="group"><span>纵轴</span><div class="seg" data-key="scale"><button data-v="linear">线性</button><button data-v="log">对数</button></div></div>
    <div class="group"><span>视图</span><div class="seg" data-key="view"><button data-v="chart">图</button><button data-v="table">表</button></div></div>
  </div>
  <div class="legend" id="legend"></div>
  <div id="charts"></div>
  <div class="note" id="note"></div>
</div>
<script>
const DATA = __DATA__;
const SERIES = [
  {key: "two_tier", label: "两级（含搬运等待）", color: "--s1", f: "obtained"},
  {key: "native", label: "仅一级（无搬运）", color: "--s2", f: "ideal"},
];
const CHARTS = [
  {sweep: "bw", title: "TPOT 与 L1↔L2 带宽", sub: "一级 96 GB，batch 8，单卡 DeepSeek-V4-Pro", xTitle: "带宽 TB/s（L1→L2）", unit: "TB/s"},
  {sweep: "cap", title: "TPOT 与一级容量", sub: "二级 1 TB/s，batch 8，单卡 DeepSeek-V4-Pro", xTitle: "一级容量 GB", unit: "GB"},
];
const state = {ctx: "256k", ov: Object.keys(DATA.sim)[0], scale: "linear", view: "chart", hidden: new Set()};
const css = n => getComputedStyle(document.getElementById("root")).getPropertyValue(n).trim();
const fmt = v => v == null ? "–" : (v >= 100 ? v.toFixed(0) : v.toFixed(1));

document.getElementById("ov").innerHTML = Object.keys(DATA.sim).map(k => `<button data-v="${k}">${k}</button>`).join("");
document.querySelectorAll(".seg").forEach(seg => seg.addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  state[seg.dataset.key] = b.dataset.v; render();
}));
document.getElementById("note").textContent =
  `仅一级（无搬运）：AISim 对同一批 pass 的原生定价，数据全在一级。两级：在此基础上逐层模拟从二级搬运权重和 KV 的等待。AISim ${DATA.aisim}，一级 10 TB/s，二级容量为权重加全部 KV，理想链路，layer_partition，合成路由（重合度为一个 token 本步专家与上一步相同的比例）。`;

function points(chart, s) {
  const pts = ((DATA.sim[state.ov] || {})[chart.sweep] || {})[state.ctx] || [];
  return pts.filter(p => p[s.f] != null).map(p => ({x: p.x, y: p[s.f], p}));
}
function xValues(chart) {
  const xs = new Set();
  SERIES.forEach(s => points(chart, s).forEach(p => xs.add(p.x)));
  return [...xs].sort((a, b) => a - b);
}
function renderLegend() {
  const el = document.getElementById("legend");
  el.innerHTML = SERIES.map(s => `<button data-k="${s.key}" aria-pressed="${!state.hidden.has(s.key)}"><i style="border-color:var(${s.color})"></i>${s.label}</button>`).join("");
  el.querySelectorAll("button").forEach(b => b.onclick = () => {
    state.hidden.has(b.dataset.k) ? state.hidden.delete(b.dataset.k) : state.hidden.add(b.dataset.k); render();
  });
}
function niceTicks(max) {
  const steps = [5, 10, 20, 25, 50, 100]; const raw = max / 5;
  const step = steps.find(s => s >= raw) || Math.ceil(raw / 100) * 100;
  const top = Math.ceil(max / step) * step;
  const out = []; for (let v = 0; v <= top + 1e-9; v += step) out.push(v); return out;
}
function drawChart(chart) {
  const W = 760, H = 330, m = {l: 52, r: 96, t: 12, b: 44};
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const xs = xValues(chart);
  const lx = v => Math.log2(v), x0 = lx(xs[0]), x1 = lx(xs[xs.length - 1]);
  const X = v => m.l + (lx(v) - x0) / (x1 - x0) * iw;
  const visible = SERIES.filter(s => !state.hidden.has(s.key));
  const ys = visible.flatMap(s => points(chart, s).map(p => p.y));
  const ymax = Math.max(10, ...ys) * 1.06;
  let Y, ticks;
  if (state.scale === "log") {
    const lo = 10, hi = Math.max(20, ...ys) * 1.15;
    Y = v => m.t + ih - (Math.log10(v) - Math.log10(lo)) / (Math.log10(hi) - Math.log10(lo)) * ih;
    ticks = [10, 20, 50, 100, 200, 500].filter(t => t <= hi);
  } else {
    ticks = niceTicks(ymax); const top = ticks[ticks.length - 1];
    Y = v => m.t + ih - v / top * ih;
  }
  let g = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${chart.title}">`;
  ticks.forEach(t => { const y = Y(t); g += `<line x1="${m.l}" x2="${m.l + iw}" y1="${y}" y2="${y}" stroke="var(--grid)" stroke-width="1"/><g class="tick"><text x="${m.l - 8}" y="${y + 4}" text-anchor="end">${t}</text></g>`; });
  xs.forEach(v => { g += `<g class="tick"><text x="${X(v)}" y="${m.t + ih + 18}" text-anchor="middle">${v}</text></g>`; });
  g += `<line x1="${m.l}" x2="${m.l + iw}" y1="${m.t + ih}" y2="${m.t + ih}" stroke="var(--axis)" stroke-width="1"/>`;
  g += `<text class="axis-title" x="${m.l + iw / 2}" y="${H - 6}" text-anchor="middle">${chart.xTitle}</text>`;
  g += `<text class="axis-title" transform="translate(14 ${m.t + ih / 2}) rotate(-90)" text-anchor="middle">TPOT（ms）</text>`;
  const ends = [];
  visible.forEach(s => {
    const pts = points(chart, s); if (!pts.length) return;
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)} ${Y(p.y).toFixed(1)}`).join("");
    g += `<path d="${d}" fill="none" stroke="var(${s.color})" stroke-width="2" stroke-linejoin="round"/>`;
    pts.forEach(p => { g += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4" fill="var(${s.color})" stroke="var(--surface-1)" stroke-width="2"/>`; });
    const last = pts[pts.length - 1]; ends.push({s, y: Y(last.y)});
  });
  ends.sort((a, b) => a.y - b.y);
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 13) ends[i].y = ends[i - 1].y + 13;
  ends.forEach(e => { g += `<text x="${m.l + iw + 8}" y="${e.y + 4}" font-size="11" fill="var(--text-secondary)">${e.s.label}</text>`; });
  g += `<line class="cross" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="var(--axis)" stroke-width="1" visibility="hidden"/>`;
  g += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/></svg>`;
  const box = document.createElement("div"); box.className = "chart";
  box.innerHTML = `<h2>${chart.title}（${state.ctx === "1m" ? "1M" : "256K"} 上下文）</h2><p class="sub">${chart.sub}</p>${g}<div class="tip"></div>`;
  const svg = box.querySelector("svg"), tip = box.querySelector(".tip"), cross = box.querySelector(".cross");
  box.querySelector(".hit").addEventListener("pointermove", ev => {
    const pt = svg.createSVGPoint(); pt.x = ev.clientX; pt.y = ev.clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM().inverse());
    const xv = xs.reduce((a, b) => Math.abs(X(b) - loc.x) < Math.abs(X(a) - loc.x) ? b : a);
    cross.setAttribute("x1", X(xv)); cross.setAttribute("x2", X(xv)); cross.setAttribute("visibility", "visible");
    let rows = "", extra = "";
    visible.forEach(s => { const p = points(chart, s).find(q => q.x === xv); if (p) {
      rows += `<div class="row"><i style="border-color:var(${s.color})"></i><span>${s.label}</span><span>${fmt(p.y)} ms</span></div>`;
      if (s.key === "two_tier") extra = `<div class="row"><span>每步从二级搬运</span><span>${p.p.fetch} GB</span></div><div class="row"><span>专家命中率</span><span>${(p.p.hit * 100).toFixed(0)}%</span></div>`;
    }});
    tip.innerHTML = `<b>${xv} ${chart.unit}</b>${rows}${extra}`;
    tip.style.display = "block";
    const r = box.getBoundingClientRect(), sr = svg.getBoundingClientRect();
    const px = sr.left - r.left + X(xv) / 760 * sr.width;
    tip.style.left = Math.min(px + 12, r.width - tip.offsetWidth - 4) + "px";
    tip.style.top = (sr.top - r.top + 16) + "px";
  });
  box.querySelector(".hit").addEventListener("pointerleave", () => { tip.style.display = "none"; cross.setAttribute("visibility", "hidden"); });
  return box;
}
function drawTable(chart) {
  const xs = xValues(chart), shown = SERIES.filter(s => !state.hidden.has(s.key));
  let h = `<div class="chart"><h2>${chart.title}（${state.ctx === "1m" ? "1M" : "256K"} 上下文，单位 ms）</h2><table><tr><th>${chart.xTitle}</th>${shown.map(s => `<th>${s.label}</th>`).join("")}</tr>`;
  xs.forEach(x => { h += `<tr><td>${x}</td>${shown.map(s => { const p = points(chart, s).find(q => q.x === x); return `<td>${p ? fmt(p.y) : "–"}</td>`; }).join("")}</tr>`; });
  return h + "</table></div>";
}
function render() {
  document.querySelectorAll(".seg").forEach(seg => seg.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(state[seg.dataset.key] === b.dataset.v))));
  renderLegend();
  const el = document.getElementById("charts"); el.innerHTML = "";
  CHARTS.forEach(c => state.view === "table" ? el.insertAdjacentHTML("beforeend", drawTable(c)) : el.appendChild(drawChart(c)));
  parent.postMessage({kvReplayHeight: document.documentElement.scrollHeight + 4}, "*");
}
window.addEventListener("resize", () => parent.postMessage({kvReplayHeight: document.documentElement.scrollHeight + 4}, "*"));
render();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*", type=Path,
                        default=[HERE / "output" / "curves", HERE / "output" / "curves-overlap0.9"])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sim, aisim = {}, set()
    for run in args.runs:
        overlap, data, commit = simulated(run)
        sim[overlap] = data
        aisim.add(commit)
    data = {"sim": sim, "aisim": "、".join(sorted(aisim))}
    args.out.write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e3:.1f} kB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import html
import json
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from matvix.state.scores import component_contributions
from matvix.storage import read_json

EVENT_LABELS = {
    "acute_front_stress_5d": "5日内急性前端压力",
    "front_inversion_5d": "5日内前端倒挂",
    "broad_persistent_stress_20d": "20日内广泛持续压力",
    "fast_repair_5d": "5日内快速修复",
}
EVENT_DEFINITIONS = {
    "acute_front_stress_5d": "未来5个交易日内是否出现 hard_acute",
    "front_inversion_5d": "未来5个交易日内是否出现 FrontSlope30<0",
    "broad_persistent_stress_20d": "未来20日内是否有任意5日窗口至少3日持续压力",
    "fast_repair_5d": "未来5个交易日内是否出现 repair_confirmed",
}
SCORE_LABELS = {
    "carry_risk": "CarryRisk",
    "shock": "Shock",
    "tail_price": "TailPrice",
    "persistence": "Persistence",
    "repair": "Repair",
}

AXIS_ORDER = ("carry_risk", "shock", "tail_price", "persistence", "repair")
ANSWER_BY_AXIS = {
    "carry_risk": "carry",
    "shock": "shock",
    "tail_price": "tail",
    "persistence": "persistence",
    "repair": "repair",
}
AXIS_UI = {
    "carry_risk": {
        "question": "Carry 是否受损？",
        "caption": "前端曲线与基差的缓冲空间",
        "tone": "#27c4db",
    },
    "shock": {
        "question": "短端是否抢险？",
        "caption": "前端保险价格的即时热度",
        "tone": "#ff7a1a",
    },
    "tail_price": {
        "question": "尾部是否昂贵？",
        "caption": "下行尾部相对中心的定价",
        "tone": "#22c7d8",
    },
    "persistence": {
        "question": "压力是否扩散？",
        "caption": "中期限与曲线广度确认",
        "tone": "#ffb21f",
    },
    "repair": {
        "question": "高压后是否修复？",
        "caption": "独立修复轴；越高代表修复证据越强",
        "tone": "#83b94a",
    },
}
ANSWER_LABELS = {
    "carry": {
        "SUPPORTIVE": "仍有缓冲",
        "MIXED": "条件混合",
        "STRESSED": "结构受损",
        "INVERTED": "前端倒挂",
        "UNKNOWN": "暂不可判",
    },
    "shock": {
        "CALM": "保持冷静",
        "BUILDING": "开始升温",
        "HIGH": "压力偏高",
        "ACUTE": "急性抢险",
        "UNKNOWN": "暂不可判",
    },
    "tail": {
        "NORMAL": "正常",
        "ELEVATED": "开始突出",
        "RICH": "尾部偏贵",
        "EXTREME": "历史极端",
        "UNKNOWN": "暂不可判",
    },
    "persistence": {
        "NORMAL": "尚未扩散",
        "FRONT_LOCALIZED": "集中前端",
        "DIFFUSING": "正在扩散",
        "PERSISTENT": "持续高压",
        "MIXED": "证据混合",
        "UNKNOWN": "暂不可判",
    },
    "repair": {
        "INACTIVE": "未进入修复",
        "BUILDING": "修复形成中",
        "CONFIRMED": "修复已确认",
        "UNKNOWN": "暂不可判",
    },
}
EVENT_ORDER = (
    "acute_front_stress_5d",
    "front_inversion_5d",
    "broad_persistent_stress_20d",
    "fast_repair_5d",
)
PRESSURE_LABELS = {
    "LOW": "低压",
    "WATCH": "观察态",
    "ELEVATED": "压力抬升",
    "HIGH": "高压",
    "EXTREME": "极端压力",
    "UNKNOWN": "暂不可判",
}
DIRECTION_LABELS = {
    "RISING": "正在升温",
    "STABLE": "大体稳定",
    "FALLING": "正在降温",
    "UNKNOWN": "方向未知",
}
DATA_STATUS_LABELS = {
    "OK": "数据完整",
    "PARTIAL": "数据部分可用",
    "UNKNOWN": "数据不足",
}
PHASE_LABELS = {
    "UNKNOWN": "数据不足",
    "ACUTE_FRONT_STRESS": "急性前端压力",
    "REPAIR_IN_PROGRESS": "修复进行中",
    "BROAD_PERSISTENT_STRESS": "广泛持续压力",
    "CALENDAR_LOCALIZED_PREMIUM": "日历窗口溢价",
    "PRESSURE_BUILDING": "压力累积",
    "TAIL_RICH_QUIET_CURVE": "平静曲线下尾部偏贵",
    "CARRY_SUPPORTIVE_LOW_STRESS": "Carry 友好低压",
    "MIXED_TRANSITION": "证据分化过渡态",
}
FEATURE_SHORT_LABELS = {
    "d1_log_vix": "VIX",
    "d5_log_vix": "VIX",
    "d5_skew": "SKEW",
    "skew_close": "SKEW",
    "front_slope30": "VX 曲线",
    "d5_front_slope30": "VX 曲线",
    "basis30_eod": "Basis",
    "near_stress_log_ratio": "VIX9D / VIX",
    "vvix_close": "VVIX",
    "d5_log_vvix": "VVIX",
    "fvol_30_93": "中期限波动",
    "fvol_93_184": "远期限波动",
    "d5_fvol_30_93": "期限扩散",
    "curve_inversion_share": "倒挂广度",
}

LIVE_STATUS_SCRIPT = """
<script id="matvix-runtime-poll">
(() => {
  const timers = new Map();
  let reloadRequested = false;

  const STATUS_LABELS = {
    PUBLISHED: "更新完成",
    ALREADY_CURRENT: "已是最新",
    NOT_DUE: "等待正式更新时间",
    SOURCES_PENDING: "等待数据源齐备",
    BUSY: "已有更新任务运行中",
    WINDOW_EXHAUSTED: "本轮等待结束，保留上一完整截面",
    FAILED: "更新失败，保留上一完整截面",
    DASHBOARD_RENDER_FAILED: "新截面展示失败，保留上一可用页面",
    RUNNING: "系统运行",
    DEGRADED: "系统降级"
  };

  function formatEtTime(value) {
    if (!value) return null;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return String(value);
    return `${new Intl.DateTimeFormat("zh-CN", {
      timeZone: "America/New_York",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    }).format(parsed)} ET`;
  }

  function applyStatus(payload) {
    if (!payload || typeof payload !== "object") return;
    const runtime = document.getElementById("runtime-status");
    const runtimeText = document.getElementById("runtime-status-text");
    const update = payload.update && typeof payload.update === "object" ? payload.update : payload;
    const renderFailure = payload.render_failure || payload.dashboard_error;
    const latest = payload.latest_snapshot_session || payload.last_good_session;
    const lastGood = payload.last_good_session || latest;
    const current = document.body.dataset.sessionDate;
    const currentRevision = document.body.dataset.dashboardRevision;
    const revisionChanged = payload.dashboard_revision && currentRevision
      && payload.dashboard_revision !== currentRevision;
    if (runtimeText) {
      const rawStatus = payload.runtime_status === "DASHBOARD_RENDER_FAILED"
        ? payload.runtime_status
        : (update.status && update.status !== "UNKNOWN"
          ? update.status
          : payload.runtime_status);
      const parts = [STATUS_LABELS[rawStatus] || String(rawStatus || "状态已更新")];
      if (lastGood) parts.push(`最近完整截面 ${lastGood}`);
      if (renderFailure?.candidate_session) {
        parts.push(`待展示截面 ${renderFailure.candidate_session}`);
      }
      const updatedAt = update.updated_at || payload.last_update_at;
      if (updatedAt && !update.next_check_at) parts.push(`更新 ${formatEtTime(updatedAt)}`);
      if (update.next_check_at) parts.push(`下次检查 ${formatEtTime(update.next_check_at)}`);
      if ((latest && current && latest !== current) || revisionChanged) {
        parts.push("新截面可用，刷新页面查看");
        if (runtime) runtime.dataset.newSnapshot = "true";
      }
      runtimeText.textContent = parts.join(" · ");
    }
    document.dispatchEvent(new CustomEvent("matvix:status", { detail: payload }));
    if ((latest && current && latest !== current) || revisionChanged) {
      document.dispatchEvent(new CustomEvent("matvix:new-snapshot", { detail: payload }));
      if (!reloadRequested) {
        reloadRequested = true;
        window.location.reload();
      }
    }
  }

  function stopStatusPolling(key = "default") {
    const timer = timers.get(key);
    if (timer) window.clearInterval(timer);
    timers.delete(key);
  }

  function startStatusPolling({
    url = document.body.dataset.statusEndpoint,
    intervalMs = 60000,
    key = "default"
  } = {}) {
    if (!url || !/^https?:$/.test(window.location.protocol)) return false;
    stopStatusPolling(key);
    const poll = async () => {
      try {
        const response = await fetch(url, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        applyStatus(await response.json());
      } catch (error) {
        document.dispatchEvent(new CustomEvent("matvix:status-error", { detail: error }));
      }
    };
    void poll();
    timers.set(key, window.setInterval(poll, Math.max(5000, Number(intervalMs) || 60000)));
    return true;
  }

  function openPanel(id, trigger) {
    const panel = document.getElementById(id);
    if (!panel) return;
    if (panel.tagName === "DETAILS") panel.open = true;
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    panel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.querySelectorAll("[data-open-panel]").forEach((trigger) => {
    trigger.addEventListener("click", () => openPanel(trigger.dataset.openPanel, trigger));
  });

  window.MatVIXDashboard = {
    applyStatus,
    openPanel,
    startStatusPolling,
    stopStatusPolling
  };
  if (/^https?:$/.test(window.location.protocol)) startStatusPolling();
})();
</script>
"""

DASHBOARD_STYLES = """
:root {
  --bg: #06101d;
  --panel: #0b1627;
  --panel-strong: #0d1a2d;
  --panel-soft: #101d31;
  --text: #f2f5fb;
  --muted: #9aa7ba;
  --line: #35445b;
  --cyan: #27c4db;
  --orange: #ff9f1a;
  --red: #ff4e3d;
  --green: #83b94a;
  --blue: #268cff;
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font: 15px/1.5 -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
}
button, summary { font: inherit; }
button:focus-visible, summary:focus-visible {
  outline: 3px solid rgba(39, 196, 219, .45);
  outline-offset: 3px;
}
.topbar {
  min-height: 60px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 10px 28px;
}
.brand { font-size: 23px; font-weight: 760; letter-spacing: .02em; white-space: nowrap; }
.freshness { flex: 1; color: #c2c9d6; }
.freshness .dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #32d286;
  margin: 0 10px 0 4px;
}
.freshness .dot.not-ok { background: var(--orange); }
.method-button {
  color: #cbd3df;
  border: 1px solid var(--line);
  background: transparent;
  border-radius: 8px;
  padding: 8px 14px;
  cursor: pointer;
}
main { max-width: 1420px; margin: 0 auto; padding: 14px 28px 48px; }
.weather-hero { text-align: center; }
.verdict {
  margin: 2px 0 0;
  font-size: clamp(22px, 2vw, 30px);
  font-weight: 760;
  letter-spacing: .01em;
}
.verdict strong { color: var(--orange); }
.main-gauge-shell { max-width: 1000px; height: 248px; margin: -2px auto 0; position: relative; }
.main-gauge-wrap { max-width: 900px; margin: 0 auto; }
.scale-edges {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 5px;
  display: flex;
  justify-content: space-between;
  padding: 0 18px;
  font-size: 15px;
  font-weight: 700;
}
.scale-edges span:first-child { color: #3197ff; }
.scale-edges span:last-child { color: var(--red); }
.weather-label {
  color: var(--muted);
  position: absolute;
  inset: 70px 0 auto;
  pointer-events: none;
}
.weather-score { color: #f2f5fb; font-size: 64px; line-height: .95; font-weight: 780; }
.weather-score span { color: #8f9bb0; font-size: 20px; font-weight: 500; }
.weather-state { font-size: 25px; font-weight: 760; color: var(--orange); }
.state-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0 5px;
  padding: 6px 22px;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--orange);
  font-weight: 700;
}
.hero-copy { color: #aab4c5; margin: 0 auto 12px; max-width: 920px; }
.triad {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 0;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  overflow: hidden;
}
.triad-card { position: relative; min-height: 198px; padding: 8px 18px 8px; text-align: center; }
.triad-card + .triad-card { border-left: 1px solid #243249; }
.instrument-title { font-size: 18px; font-weight: 700; margin-top: 2px; }
.instrument-title.orange { color: var(--orange); }
.instrument-title.cyan { color: var(--cyan); }
.instrument-title.muted { color: #b5becc; }
.instrument-plot { margin: -4px auto 0; max-width: 360px; }
.instrument-answer { font-weight: 740; font-size: 18px; margin-top: -3px; }
.instrument-copy { color: var(--muted); font-size: 13px; margin-top: 2px; }
.driver-line { color: #cbd3df; font-size: 13px; margin-top: 2px; }
.stability-note { color: #8290a6; font-size: 12px; margin-top: 2px; }
.axes-section { margin-top: 10px; }
.section-kicker { margin: 0 0 4px 10px; font-size: 18px; }
.section-kicker small { color: var(--muted); font-size: 13px; font-weight: 400; }
.axis-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 4px; }
.axis-card { min-width: 0; text-align: center; padding: 2px 8px 8px; }
.axis-card.repair-axis { border-left: 1px dashed #526077; padding-left: 16px; }
.axis-question { color: #c6ceda; min-height: 25px; }
.axis-answer { min-height: 28px; font-size: 19px; font-weight: 760; }
.axis-plot { margin: -12px auto 0; }
.axis-name { color: #aeb8c7; font-size: 14px; }
.axis-caption { color: #75849b; font-size: 11px; min-height: 17px; }
.probability-strip {
  margin-top: 8px;
  border: 1px solid var(--line);
  border-radius: 14px;
  background: var(--panel);
  display: grid;
  grid-template-columns: 220px 1fr;
  align-items: stretch;
  overflow: hidden;
}
.prob-heading { padding: 10px 18px; border-right: 1px solid #243249; }
.prob-heading h2 { margin: 0; font-size: 18px; }
.prob-heading p { margin: 3px 0 0; color: var(--muted); font-size: 12px; }
.prob-summary-grid {
  display: grid;
  grid-template-columns: repeat(var(--summary-count, 3), minmax(0, 1fr));
}
.prob-summary-card { padding: 6px 18px; min-width: 0; }
.prob-summary-card + .prob-summary-card { border-left: 1px dashed #3a465b; }
.prob-summary-card h3 { margin: 0; font-size: 14px; font-weight: 560; color: #c8d0dc; }
.prob-value { font-size: 27px; line-height: 1.05; font-weight: 760; margin: 2px 0 1px; }
.prob-base { color: #aab3c1; font-size: 12px; }
.prob-mode { display: inline-block; margin-top: 2px; font-size: 10px; border-radius: 999px; padding: 1px 7px; }
.prob-mode.qualified { color: #83c9ff; border: 1px solid #245885; }
.prob-mode.historical { color: #c8d0dc; border: 1px solid #465266; }
.prob-mode.inactive { color: #8996a9; border: 1px solid #39465a; }
.actions { display: flex; justify-content: center; gap: 16px; margin: 9px 0 4px; }
.action-button {
  min-width: 260px;
  min-height: 54px;
  border-radius: 8px;
  border: 1px solid #58667d;
  color: #eaf0f8;
  background: transparent;
  font-size: 18px;
  cursor: pointer;
}
.action-button.primary { background: #26bdd1; color: #05111e; border-color: #26bdd1; font-weight: 720; }
.detail-panel { margin-top: 18px; border: 1px solid var(--line); border-radius: 14px; background: var(--panel); }
.detail-panel > summary { padding: 15px 18px; cursor: pointer; font-size: 18px; font-weight: 700; }
.detail-content { padding: 0 18px 20px; }
.conflict-summary { color: #d7dde7; padding: 12px 14px; border-left: 3px solid var(--orange); background: var(--panel-soft); }
.grid { display: grid; gap: 14px; }
.evidence-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 14px; }
.curves { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.scores, .answers { grid-template-columns: repeat(5, minmax(0, 1fr)); }
.probs { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.box, .score-card, .answer, .prob-card {
  background: var(--panel-soft);
  border: 1px solid #2e3a4f;
  border-radius: 12px;
  padding: 14px;
}
.score-card span, .answer small { display: block; color: var(--muted); }
.score-card strong { font-size: 26px; }
.prob-card h3 { min-height: 44px; }
.probability { font-size: 26px; font-weight: 760; margin: 8px 0; }
section.deep-section { margin-top: 22px; }
section.deep-section h2 { font-size: 18px; margin: 0 0 10px; }
ul { margin: 0; padding-left: 20px; }
li { margin: 0 0 9px; }
dl { display: grid; grid-template-columns: 1fr 1fr; margin: 0; }
dt { color: var(--muted); }
dd { text-align: right; margin: 0; }
table { width: 100%; border-collapse: collapse; background: var(--panel-soft); border-radius: 12px; overflow: hidden; }
th, td { padding: 10px 12px; border-bottom: 1px solid #2d394d; text-align: right; }
th:first-child, td:first-child { text-align: left; }
pre { white-space: pre-wrap; overflow: auto; color: #d1d9e6; }
.diagnostics { margin-top: 16px; }
.diagnostics summary { cursor: pointer; color: #cbd4e2; }
.raw-enum { color: #7e8ca1; font-size: 11px; }
.plotly-graph-div { width: 100% !important; }
@media (max-width: 980px) {
  .triad { grid-template-columns: 1fr; }
  .triad-card + .triad-card { border-left: 0; border-top: 1px solid #243249; }
  .axis-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .axis-card.repair-axis { border-left: 0; padding-left: 8px; }
  .probability-strip { grid-template-columns: 1fr; }
  .prob-heading { border-right: 0; border-bottom: 1px solid #243249; }
  .prob-summary-grid { grid-template-columns: 1fr; }
  .prob-summary-card + .prob-summary-card { border-left: 0; border-top: 1px dashed #3a465b; }
  .curves, .evidence-grid, .probs { grid-template-columns: 1fr 1fr; }
  .scores, .answers { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .main-gauge-shell { height: 248px; }
}
@media (max-width: 620px) {
  .topbar { align-items: flex-start; flex-wrap: wrap; padding: 12px 16px; }
  .freshness { order: 3; flex-basis: 100%; }
  main { padding: 14px 12px 36px; }
  .verdict { text-align: left; }
  .main-gauge-wrap { margin-top: 8px; }
  .weather-label { inset: 74px 0 auto; }
  .weather-score { font-size: 52px; }
  .axis-grid, .curves, .evidence-grid, .probs, .scores, .answers { grid-template-columns: 1fr; }
  .actions { flex-direction: column; }
  .action-button { width: 100%; min-width: 0; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
}
"""


def _fmt_score(value: Any) -> str:
    return "UNKNOWN" if value is None else f"{float(value):.1f}"


def _fmt_probability(event: dict[str, Any]) -> str:
    if event["event_status"] == "NOT_APPLICABLE":
        return "不适用 / 状态已存在"
    if event["probability"] is None:
        return "暂不发布"
    return f"{float(event['probability']):.1%}"


def _fmt_base(event: dict[str, Any]) -> str:
    return "—" if event["base_rate"] is None else f"{float(event['base_rate']):.1%}"


def _fmt_uplift(event: dict[str, Any]) -> str:
    return "—" if event["uplift"] is None else f"{float(event['uplift']) * 100:+.1f} pp"


def _numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _answer_label(axis: str, answer: Any) -> str:
    normalized = str(answer)
    return ANSWER_LABELS[axis].get(normalized, normalized)


def _indicator_html(
    value: Any,
    *,
    div_id: str,
    tone: str,
    height: int,
    include_plotlyjs: bool = False,
    annotation: str | None = None,
    annotation_size: int | None = None,
    annotation_y: float | None = None,
    compact: bool = False,
    reverse_semantics: bool = False,
    show_number: bool = True,
) -> str:
    numeric = _numeric(value)
    shown_value = 0.0 if numeric is None else max(0.0, min(100.0, numeric))
    if reverse_semantics:
        steps = [
            {"range": [0, 35], "color": "#202a3b"},
            {"range": [35, 70], "color": "#244136"},
            {"range": [70, 100], "color": "#2a593e"},
        ]
    else:
        steps = [
            {"range": [0, 35], "color": "#17365e"},
            {"range": [35, 55], "color": "#174d5f"},
            {"range": [55, 70], "color": "#604c22"},
            {"range": [70, 85], "color": "#6b3422"},
            {"range": [85, 100], "color": "#62252b"},
        ]
    mode = "gauge+number" if numeric is not None and show_number else "gauge"
    indicator = go.Indicator(
        mode=mode,
        value=shown_value,
        number={
            "font": {"color": tone, "size": 58 if not compact else 30},
            "suffix": "" if compact else "/100",
            "valueformat": ".1f" if compact else ".0f",
        },
        gauge={
            "axis": {
                "range": [0, 100],
                "tickmode": "array",
                "tickvals": [0, 50, 100],
                "ticktext": ["0", "50", "100"],
                "tickfont": {"color": "#91a0b8", "size": 9 if compact else 12},
                "tickcolor": "#53627a",
                "tickwidth": 1,
            },
            "bar": {"color": tone, "thickness": 0.17 if compact else 0.13},
            "bgcolor": "rgba(0,0,0,0)",
            "borderwidth": 0,
            "steps": steps,
            "threshold": {
                "line": {"color": "#f4f7fb", "width": 3 if compact else 4},
                "thickness": 0.82,
                "value": shown_value,
            },
        },
        domain={"x": [0, 1], "y": [0.02, 1]},
    )
    figure = go.Figure(indicator)
    annotations: list[dict[str, Any]] = []
    if numeric is None and show_number:
        annotations.append(
            {
                "x": 0.5,
                "y": 0.31,
                "text": "暂无",
                "showarrow": False,
                "font": {"color": "#c4cddd", "size": 22},
            }
        )
    if annotation:
        annotations.append(
            {
                "x": 0.5,
                "y": annotation_y if annotation_y is not None else (0.08 if compact else 0.12),
                "text": annotation,
                "showarrow": False,
                "font": {
                    "color": "#eef3fb",
                    "size": annotation_size or (12 if compact else 16),
                },
            }
        )
    figure.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 8, "b": 2},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={
            "family": '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
            "color": "#eef3fb",
        },
        annotations=annotations,
    )
    return str(
        pio.to_html(
            figure,
            full_html=False,
            include_plotlyjs="inline" if include_plotlyjs else False,
            config={"displayModeBar": False, "responsive": True},
            div_id=div_id,
        )
    )


def _radial_indicator_html(
    value: Any,
    *,
    div_id: str,
    tone: str,
    label: str,
    height: int = 150,
    show_value: bool = True,
    secondary: str | None = None,
) -> str:
    """Render the selected trader mock's segmented 270-degree instrument ring."""
    numeric = _numeric(value)
    shown_value = 0.0 if numeric is None else max(0.0, min(100.0, numeric))
    segment_count = 20
    active_segments = segment_count if not show_value else round(shown_value / 100 * segment_count)
    segment_values = [75.0 / segment_count] * segment_count
    colors = [tone if index < active_segments else "#273247" for index in range(segment_count)]
    figure = go.Figure(
        go.Pie(
            values=[*segment_values, 25.0],
            labels=[*("" for _ in range(segment_count)), ""],
            marker={"colors": [*colors, "rgba(0,0,0,0)"], "line": {"color": "#0b1220", "width": 3}},
            hole=0.70,
            rotation=135,
            direction="clockwise",
            sort=False,
            textinfo="none",
            hoverinfo="skip",
            showlegend=False,
        )
    )
    if show_value:
        primary = "—" if numeric is None else f"{shown_value:.1f}"
        primary_size = 34
        primary_color = tone
    else:
        primary = label
        primary_size = 27
        primary_color = "#eef3fb"
    annotations: list[dict[str, Any]] = [
        {
            "x": 0.5,
            "y": 0.56,
            "text": primary,
            "showarrow": False,
            "font": {"color": primary_color, "size": primary_size},
        },
        {
            "x": 0.5,
            "y": 0.39,
            "text": label if show_value else (secondary or ""),
            "showarrow": False,
            "font": {"color": tone if show_value else "#aab4c5", "size": 17},
        },
    ]
    figure.update_layout(
        height=height,
        margin={"l": 2, "r": 2, "t": 0, "b": 0},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={
            "family": '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
            "color": "#eef3fb",
        },
        annotations=annotations,
    )
    return str(
        pio.to_html(
            figure,
            full_html=False,
            include_plotlyjs=False,
            config={"displayModeBar": False, "responsive": True},
            div_id=div_id,
        )
    )


def _verdict(story: dict[str, Any], data_status: str) -> str:
    if data_status != "OK":
        return "核心数据不足，暂不形成市场判断"
    phase = str(story.get("phase", "UNKNOWN"))
    direction = str(story.get("direction", "UNKNOWN"))
    triggers = story.get("structural_triggers") or []
    if phase == "ACUTE_FRONT_STRESS":
        return "急性前端压力已经确认"
    if phase == "BROAD_PERSISTENT_STRESS":
        return "压力已经扩散，并形成持续性高压"
    if phase == "REPAIR_IN_PROGRESS":
        return "高压仍在，但边际修复正在进行"
    if direction == "RISING" and not triggers:
        return "风险正在升温，结构性压力尚未确认"
    if direction == "FALLING":
        return f"风险正在降温，当前仍属{PHASE_LABELS.get(phase, phase)}"
    return PHASE_LABELS.get(phase, str(story.get("headline", phase)))


def _market_summary(story: dict[str, Any], diagnostics: dict[str, Any]) -> str:
    answers = story.get("answers", {})
    parts = [
        {
            "CALM": "短端保险价格保持冷静",
            "BUILDING": "短端保险定价开始升温",
            "HIGH": "短端保险价格快速重定价",
            "ACUTE": "短端保险已进入急性重定价",
            "UNKNOWN": "短端热度暂不可判",
        }.get(str(answers.get("shock")), "短端热度信号已更新"),
        {
            "SUPPORTIVE": "前端曲线与基差仍有缓冲",
            "MIXED": "Carry 条件并不清晰",
            "STRESSED": "Carry 结构正在受损",
            "INVERTED": "前端曲线已经倒挂",
            "UNKNOWN": "Carry 条件暂不可判",
        }.get(str(answers.get("carry")), "Carry 状态已更新"),
    ]
    if diagnostics.get("hard_acute") is False:
        parts.append("尚无急性硬确认")
    return "；".join(parts)


def _feature_sources(items: list[dict[str, Any]], *, empty: str) -> str:
    labels: list[str] = []
    for item in items:
        feature = str(item.get("feature", ""))
        label = FEATURE_SHORT_LABELS.get(feature, feature or "指标")
        if label not in labels:
            labels.append(label)
    return " · ".join(labels[:3]) or empty


def _axis_feature_sources(
    history: pd.DataFrame | None,
    session_date: Any,
    *,
    axis: str,
    high: bool,
) -> list[str] | None:
    """Rank one axis from its untruncated frozen component contributions."""
    if history is None or history.empty or "session_date" not in history:
        return None
    dates = pd.to_datetime(history["session_date"], errors="coerce").dt.normalize()
    rows = history.loc[dates.eq(pd.Timestamp(session_date).normalize())]
    if rows.empty:
        return None
    return _axis_sources_from_contributions(
        component_contributions(rows.iloc[-1]),
        axis=axis,
        high=high,
    )


def _axis_sources_from_contributions(
    contributions: list[dict[str, Any]],
    *,
    axis: str,
    high: bool,
) -> list[str]:
    records = [
        record
        for record in contributions
        if record.get("axis") == axis
        and (
            float(cast(Any, record["percentile"])) >= 0.5
            if high
            else float(cast(Any, record["percentile"])) <= 0.5
        )
    ]
    records.sort(
        key=lambda record: (
            -float(cast(Any, record["contribution"]))
            if high
            else float(cast(Any, record["contribution"])),
            str(record["id"]),
        )
    )
    labels: list[str] = []
    for record in records:
        feature_refs = record.get("feature_refs")
        feature = str(feature_refs[0]) if isinstance(feature_refs, list) and feature_refs else ""
        label = FEATURE_SHORT_LABELS.get(feature, feature or "指标")
        if label not in labels:
            labels.append(label)
    return labels[:3]


def _probability_mode_label(event: dict[str, Any]) -> tuple[str, str]:
    status = str(event.get("model_status", ""))
    if status == "CALIBRATED_MODEL":
        return "特征条件概率", "qualified"
    if status == "BASE_RATE_ONLY":
        return "仅历史频率 · 不是当前信号", "historical"
    if event.get("event_status") == "NOT_APPLICABLE":
        return "当前条件不适用", "inactive"
    return "当前不发布模型判断", "inactive"


def _outlook_label(outlook: Any) -> str:
    return {
        "NO_STRONG_EDGE": "暂无强概率优势",
        "BASE_RATE_ONLY": "当前仅有历史基准",
        "NOT_APPLICABLE": "当前转移问题不适用",
        "UNKNOWN": "概率判断暂不可用",
    }.get(str(outlook), EVENT_LABELS.get(str(outlook), str(outlook)))


def _decision_label(value: Any) -> str:
    if value is None:
        return "—"
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    return str(timestamp.strftime("%Y-%m-%d %H:%M ET"))


def _evidence_html(items: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for item in items:
        if item["evidence_id"] == "persistence.curve_breadth":
            ratio = item["raw_value"] if item["raw_value"] is not None else item["percentile"]
            detail = f"{item['feature']} · 期限倒挂广度比例={float(ratio):.1%}"
        else:
            detail = f"{item['feature']} · 历史方向分位={float(item['percentile']):.3f}"
        rows.append(
            f"<li><b>{html.escape(item['meaning'])}</b><br><small>{html.escape(detail)}</small></li>"
        )
    return "".join(rows) or "<li>无满足排序阈值的证据</li>"


def _plain_list_html(items: list[str], *, empty: str) -> str:
    return (
        "".join(f"<li>{html.escape(item)}</li>" for item in items)
        or f"<li>{html.escape(empty)}</li>"
    )


def _curve_html(snapshot: dict[str, Any]) -> tuple[str, str]:
    observations = snapshot.get("observations", {})
    iv_values = [
        observations.get("vix9d_close"),
        observations.get("vix_close"),
        observations.get("vix3m_close"),
        observations.get("vix6m_close"),
    ]
    iv = go.Figure()
    iv.add_trace(
        go.Scatter(
            x=[9, 30, 93, 184],
            y=iv_values,
            mode="lines+markers",
            line={"color": "#28c5d8", "width": 3},
            marker={"size": 8},
        )
    )
    iv.update_layout(
        title="SPX 隐含波动率目标期限曲线",
        xaxis_title="目标日数",
        yaxis_title="指数点",
        height=330,
        margin=dict(l=45, r=20, t=55, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0b1424",
        font={"color": "#c9d3e3"},
        xaxis={"gridcolor": "#243249"},
        yaxis={"gridcolor": "#243249"},
    )
    vx_settles = observations.get("vx_settles") or []
    vx_ids = observations.get("vx_contract_ids") or []
    vx = go.Figure()
    vx.add_trace(
        go.Scatter(
            x=vx_ids,
            y=vx_settles,
            mode="lines+markers",
            line={"color": "#ff9b1f", "width": 3},
            marker={"size": 8},
        )
    )
    vx.update_layout(
        title="标准月 VX F1–F6 官方结算曲线",
        xaxis_title="合约",
        yaxis_title="VIX 点",
        height=330,
        margin=dict(l=45, r=20, t=55, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0b1424",
        font={"color": "#c9d3e3"},
        xaxis={"gridcolor": "#243249"},
        yaxis={"gridcolor": "#243249"},
    )
    return (
        pio.to_html(
            iv, full_html=False, include_plotlyjs=False, config={"displayModeBar": False}
        ),
        pio.to_html(vx, full_html=False, include_plotlyjs=False, config={"displayModeBar": False}),
    )


def _change_table(snapshot: dict[str, Any], history: pd.DataFrame | None) -> str:
    session = pd.Timestamp(snapshot["session_date"])
    metrics = [
        ("BaselineScore", "baseline_score"),
        ("VIX", "vix_close"),
        ("VXCM30", "vxcm30"),
        ("FrontSlope30", "front_slope30"),
        ("NearStress", "near_stress_log_ratio"),
    ]
    rows: list[str] = []
    if history is None or history.empty or "session_date" not in history:
        for label, _ in metrics:
            rows.append(f"<tr><td>{label}</td><td>—</td><td>—</td><td>—</td></tr>")
    else:
        frame = history.copy()
        frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
        frame = frame.loc[frame["session_date"] <= session].sort_values("session_date")
        if frame.empty:
            return ""
        current = frame.iloc[-1]
        for label, field in metrics:
            values: list[str] = []
            for lag in (1, 5, 20):
                if (
                    field not in frame
                    or len(frame) <= lag
                    or pd.isna(current.get(field))
                    or pd.isna(frame.iloc[-1 - lag].get(field))
                ):
                    values.append("—")
                else:
                    values.append(
                        f"{float(current[field]) - float(frame.iloc[-1 - lag][field]):+.3f}"
                    )
            rows.append(
                f"<tr><td>{html.escape(label)}</td><td>{values[0]}</td><td>{values[1]}</td><td>{values[2]}</td></tr>"
            )
    return (
        "<table><thead><tr><th>指标</th><th>1日</th><th>5日</th><th>20日</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def _history_chart(history: pd.DataFrame | None, session: str) -> str:
    if history is None or history.empty or "session_date" not in history:
        return '<div class="box">暂无状态历史</div>'
    frame = history.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    frame = frame.loc[frame["session_date"] <= pd.Timestamp(session)].tail(252)
    figure = go.Figure()
    for field, label, color in (
        ("baseline_score", "Baseline", "#f2f5fb"),
        ("carry_risk_score", "CarryRisk", "#28c5d8"),
        ("shock_score", "Shock", "#ff7a1a"),
        ("tail_price_score", "TailPrice", "#29a9ff"),
        ("persistence_score", "Persistence", "#ffb21f"),
        ("repair_score", "Repair", "#83b94a"),
    ):
        if field in frame:
            figure.add_trace(
                go.Scatter(
                    x=frame["session_date"],
                    y=frame[field],
                    mode="lines",
                    name=label,
                    line={"color": color, "width": 2},
                )
            )
    figure.update_layout(
        title="过去252个交易日状态分数路径",
        height=380,
        margin=dict(l=45, r=20, t=55, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0b1424",
        font={"color": "#c9d3e3"},
        xaxis={"gridcolor": "#243249"},
        yaxis={"range": [0, 100], "gridcolor": "#243249"},
    )
    return str(
        pio.to_html(
            figure,
            full_html=False,
            include_plotlyjs=False,
            config={"displayModeBar": False},
        )
    )


def _probability_history_chart(oof: pd.DataFrame | None, session: str) -> str:
    required = {"event_id", "prediction_date", "calibrated_probability", "base_rate_at_prediction"}
    if oof is None or oof.empty or not required.issubset(oof.columns):
        return '<div class="box">当前没有可展示的 calibrated OOF 概率路径</div>'
    frame = oof.copy()
    frame["prediction_date"] = pd.to_datetime(frame["prediction_date"]).dt.normalize()
    frame = frame.loc[frame["prediction_date"] <= pd.Timestamp(session)]
    figure = go.Figure()
    for event_id, event_frame in frame.groupby("event_id", sort=False):
        event_frame = event_frame.sort_values("prediction_date").tail(504)
        label = EVENT_LABELS.get(str(event_id), str(event_id))
        figure.add_trace(
            go.Scatter(
                x=event_frame["prediction_date"],
                y=event_frame["calibrated_probability"],
                mode="lines",
                name=f"{label} · 模型",
            )
        )
        figure.add_trace(
            go.Scatter(
                x=event_frame["prediction_date"],
                y=event_frame["base_rate_at_prediction"],
                mode="lines",
                line={"dash": "dot"},
                name=f"{label} · BaseRate",
            )
        )
    figure.update_layout(
        title="真正样本外概率与当时历史基准路径",
        yaxis=dict(tickformat=".0%", range=[0, 1], gridcolor="#243249"),
        height=430,
        margin=dict(l=45, r=20, t=55, b=45),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0b1424",
        font={"color": "#c9d3e3"},
        xaxis={"gridcolor": "#243249"},
    )
    return str(
        pio.to_html(
            figure,
            full_html=False,
            include_plotlyjs=False,
            config={"displayModeBar": False},
        )
    )


def render_dashboard(
    snapshot: dict[str, Any],
    history: pd.DataFrame | None = None,
    oof: pd.DataFrame | None = None,
) -> str:
    story = snapshot["market_story"]
    answers = story.get("answers", {})
    scores = story.get("scores", {})
    diagnostics_map = snapshot.get("diagnostics", {})
    data_status = str(snapshot.get("data_status", "UNKNOWN"))
    data_status_label = DATA_STATUS_LABELS.get(data_status, data_status)
    decision_label = _decision_label(snapshot.get("decision_as_of"))
    baseline = story.get("baseline_score")
    carry_risk = _numeric(scores.get("carry_risk"))
    structure_stability = None if carry_risk is None else 100.0 - carry_risk
    pressure = str(story.get("pressure_level", "UNKNOWN"))
    direction = str(story.get("direction", "UNKNOWN"))
    phase = str(story.get("phase", "UNKNOWN"))
    pressure_label = PRESSURE_LABELS.get(pressure, pressure)
    direction_label = DIRECTION_LABELS.get(direction, direction)
    phase_label = PHASE_LABELS.get(phase, phase)
    structure_answer = _answer_label("carry", answers.get("carry", "UNKNOWN"))
    shock_answer = _answer_label("shock", answers.get("shock", "UNKNOWN"))
    hard_acute_copy = (
        "急性压力已确认" if diagnostics_map.get("hard_acute") else "尚未形成急性压力"
    )

    main_gauge = _indicator_html(
        baseline,
        div_id="market-weather-gauge",
        tone="#ffb21f",
        height=248,
        include_plotlyjs=True,
        show_number=False,
    )
    short_gauge = _radial_indicator_html(
        scores.get("shock"),
        div_id="short-temperature-gauge",
        tone="#ff7a1a",
        label=shock_answer,
        height=154,
    )
    composite_gauge = _radial_indicator_html(
        baseline,
        div_id="composite-judgment-gauge",
        tone="#8f9bb0",
        label=pressure_label,
        secondary=hard_acute_copy,
        height=154,
        show_value=False,
    )
    stability_gauge = _radial_indicator_html(
        structure_stability,
        div_id="structure-stability-gauge",
        tone="#27c4db",
        label=structure_answer,
        height=154,
    )

    axis_cards_parts: list[str] = []
    score_cards_parts: list[str] = []
    answer_cards_parts: list[str] = []
    for axis in AXIS_ORDER:
        answer_key = ANSWER_BY_AXIS[axis]
        raw_answer = str(answers.get(answer_key, "UNKNOWN"))
        answer_label = _answer_label(answer_key, raw_answer)
        ui = AXIS_UI[axis]
        tone = str(ui["tone"])
        gauge = _indicator_html(
            scores.get(axis),
            div_id=f"axis-{axis.replace('_', '-')}-gauge",
            tone=tone,
            height=92,
            compact=True,
            reverse_semantics=axis == "repair",
        )
        repair_class = " repair-axis" if axis == "repair" else ""
        direction_hint = "修复证据分" if axis == "repair" else "风险分"
        axis_cards_parts.append(
            f"""<article class="axis-card{repair_class}" data-axis="{html.escape(axis)}">
              <div class="axis-question">{html.escape(str(ui['question']))}</div>
              <div class="axis-answer" style="color:{html.escape(tone)}">{html.escape(answer_label)}</div>
              <div class="axis-plot" role="img" aria-label="{html.escape(str(ui['question']))}，{html.escape(answer_label)}，{html.escape(_fmt_score(scores.get(axis)))} 分">{gauge}</div>
              <div class="axis-name">{html.escape(SCORE_LABELS[axis])} · {direction_hint}</div>
              <div class="axis-caption">{html.escape(str(ui['caption']))}</div>
            </article>"""
        )
        score_cards_parts.append(
            f'<div class="score-card"><span>{html.escape(SCORE_LABELS[axis])}</span><strong>{html.escape(_fmt_score(scores.get(axis)))}</strong><small>{direction_hint}</small></div>'
        )
        answer_cards_parts.append(
            f'<div class="answer"><small>{html.escape(str(ui["question"]))}</small><b>{html.escape(answer_label)}</b><div class="raw-enum">{html.escape(raw_answer)}</div></div>'
        )
    axis_cards = "".join(axis_cards_parts)
    score_cards = "".join(score_cards_parts)
    answer_cards = "".join(answer_cards_parts)

    probabilities = snapshot.get("probability_judgment", {})
    probability_cards_parts: list[str] = []
    for event_id in EVENT_ORDER:
        event = probabilities.get(event_id)
        if event is None:
            continue
        mode_label, mode_class = _probability_mode_label(event)
        probability_cards_parts.append(
            f"""<article class="prob-card" data-event="{html.escape(event_id)}">
              <h3>{html.escape(EVENT_LABELS[event_id])}</h3>
              <div class="probability">{html.escape(_fmt_probability(event))}</div>
              <div class="prob-mode {html.escape(mode_class)}">{html.escape(mode_label)}</div>
              <dl><dt>历史基准</dt><dd>{html.escape(_fmt_base(event))}</dd>
                  <dt>Uplift</dt><dd>{html.escape(_fmt_uplift(event))}</dd>
                  <dt>事件状态</dt><dd>{html.escape(str(event['event_status']))}</dd>
                  <dt>模型</dt><dd>{html.escape(str(event['model_status']))}</dd>
                  <dt>概率类型</dt><dd>{html.escape(str(event['probability_kind'] or '—'))}</dd>
                  <dt>有效至</dt><dd>{html.escape(str(event['valid_through_session'] or '—'))}</dd></dl>
              <small>{html.escape(EVENT_DEFINITIONS[event_id])}</small>
              <p>{html.escape(str(event['interpretation']))}</p>
            </article>"""
        )
    probability_cards = "".join(probability_cards_parts)

    summary_event_ids = list(EVENT_ORDER[:3])
    repair_event = probabilities.get("fast_repair_5d")
    if repair_event and repair_event.get("event_status") != "NOT_APPLICABLE":
        summary_event_ids.append("fast_repair_5d")
    summary_parts: list[str] = []
    for event_id in summary_event_ids:
        event = probabilities.get(event_id)
        if event is None:
            continue
        mode_label, mode_class = _probability_mode_label(event)
        summary_parts.append(
            f"""<article class="prob-summary-card" data-summary-event="{html.escape(event_id)}">
              <h3>{html.escape(EVENT_LABELS[event_id].replace('内', ''))}</h3>
              <div class="prob-value">{html.escape(_fmt_probability(event))}</div>
              <div class="prob-base">历史基准 {_fmt_base(event)} · {_fmt_uplift(event)}</div>
              <span class="prob-mode {html.escape(mode_class)}">{html.escape(mode_label)}</span>
            </article>"""
        )
    probability_summary = "".join(summary_parts)
    summary_count = max(1, len(summary_parts))

    iv_chart, vx_chart = _curve_html(snapshot)
    diagnostics = json.dumps(
        {
            "observations": snapshot.get("observations", {}),
            "diagnostics": diagnostics_map,
        },
        ensure_ascii=False,
        indent=2,
    )
    changes = _change_table(snapshot, history)
    history_chart = _history_chart(history, snapshot["session_date"])
    probability_history_chart = _probability_history_chart(oof, snapshot["session_date"])
    drivers = story.get("drivers") or []
    counters = story.get("counter_evidence") or []
    repair_evidence = story.get("repair_evidence") or []
    triggers = story.get("structural_triggers") or []
    changes_view = story.get("what_changes_the_view") or []
    shock_drivers = [
        item
        for item in drivers
        if str(item.get("evidence_id", "")).startswith("shock.")
    ]
    carry_counters = [
        item
        for item in counters
        if str(item.get("evidence_id", "")).startswith("carry.")
    ]
    frozen_contributions = diagnostics_map.get("component_contributions")
    shock_axis_sources: list[str] | None
    carry_axis_sources: list[str] | None
    if isinstance(frozen_contributions, list):
        normalized_contributions = [
            cast(dict[str, Any], item)
            for item in frozen_contributions
            if isinstance(item, dict)
        ]
        shock_axis_sources = _axis_sources_from_contributions(
            normalized_contributions,
            axis="shock",
            high=True,
        )
        carry_axis_sources = _axis_sources_from_contributions(
            normalized_contributions,
            axis="carry_risk",
            high=False,
        )
    else:
        shock_axis_sources = _axis_feature_sources(
            history,
            snapshot["session_date"],
            axis="shock",
            high=True,
        )
        carry_axis_sources = _axis_feature_sources(
            history,
            snapshot["session_date"],
            axis="carry_risk",
            high=False,
        )
    driver_sources = (
        " · ".join(shock_axis_sources) or "Shock 各分量均未高于历史中位"
        if shock_axis_sources is not None
        else _feature_sources(
            shock_drivers,
            empty="Shock 分量未进入全局证据榜",
        )
    )
    counter_sources = (
        " · ".join(carry_axis_sources) or "Carry 各分量均未低于历史中位"
        if carry_axis_sources is not None
        else _feature_sources(
            carry_counters,
            empty="Carry 分量未进入全局证据榜",
        )
    )
    if drivers and counters:
        conflict_summary = (
            f"升温证据与结构缓冲同时存在；当日{'已有' if triggers else '没有'}结构触发，"
            f"因此按冻结状态机发布为“{phase_label}”，而不是把五个分数简单平均。"
        )
    elif triggers:
        conflict_summary = f"结构触发已成立：{'；'.join(map(str, triggers))}。当前发布为“{phase_label}”。"
    else:
        conflict_summary = f"当前没有结构触发，冻结状态机发布为“{phase_label}”。"
    freshness_class = "" if data_status == "OK" else " not-ok"
    verdict = _verdict(story, data_status)
    market_summary = _market_summary(story, diagnostics_map)
    outlook = _outlook_label(answers.get("outlook", "UNKNOWN"))
    weather_score = "—" if _numeric(baseline) is None else f"{float(baseline):.0f}"

    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MatVIX {html.escape(snapshot["session_date"])}</title>
<style>{DASHBOARD_STYLES}</style></head>
<body data-status-endpoint="/api/status" data-session-date="{html.escape(str(snapshot['session_date']))}" data-dashboard-version="trader-v1">
<header class="topbar">
  <div class="brand">MatVIX · 期权气象站</div>
  <div class="freshness" id="runtime-status"><span class="dot{freshness_class}" aria-hidden="true"></span>
    <span id="runtime-status-text"><span data-live-field="data_status">{html.escape(data_status_label)}</span> · 数据截面
    <span data-live-field="session_date">{html.escape(str(snapshot['session_date']))}</span> · 正式可用
    <span data-live-field="decision_as_of">{html.escape(decision_label)}</span></span>
  </div>
  <button class="method-button" type="button" data-open-panel="quant-panel" aria-controls="quant-panel" aria-expanded="false">方法与口径</button>
</header>
<main>
  <section class="weather-hero" aria-labelledby="market-verdict">
    <h1 class="verdict" id="market-verdict">市场状态：<strong>{html.escape(verdict)}</strong></h1>
    <div class="main-gauge-shell">
      <div class="main-gauge-wrap" role="img" aria-label="市场天气分数 {_fmt_score(baseline)}，{html.escape(pressure_label)}">{main_gauge}</div>
      <div class="scale-edges" aria-hidden="true"><span>冷静 0</span><span>急性压力 100</span></div>
      <div class="weather-label">
        <div>市场天气</div>
        <div class="weather-score">{html.escape(weather_score)}<span>/100</span></div>
        <div class="state-pill">{html.escape(pressure_label)} <span class="raw-enum">{html.escape(pressure)}</span></div>
        <div class="weather-state">{html.escape(direction_label)}</div>
      </div>
    </div>
    <p class="hero-copy">{html.escape(market_summary)}。</p>
  </section>

  <section class="triad" aria-label="短端温度、综合判断与结构稳定度">
    <article class="triad-card">
      <div class="instrument-title orange">短端温度</div>
      <div class="instrument-plot" role="img" aria-label="短端温度等于 Shock {_fmt_score(scores.get('shock'))}">{short_gauge}</div>
      <div class="driver-line">主要驱动：{html.escape(driver_sources)}</div>
      <div class="instrument-copy">短端温度即 Shock 分数，反映前端保险价格的即时热度</div>
    </article>
    <article class="triad-card">
      <div class="instrument-title muted">综合判断</div>
      <div class="instrument-plot" role="img" aria-label="综合压力 {_fmt_score(baseline)}，{html.escape(pressure_label)}">{composite_gauge}</div>
      <div class="instrument-copy">摘要阶段：{html.escape(phase_label)}；按确认规则发布，不是五轴简单投票</div>
    </article>
    <article class="triad-card">
      <div class="instrument-title cyan">结构稳定度</div>
      <div class="instrument-plot" role="img" aria-label="结构稳定度 {_fmt_score(structure_stability)}，等于一百减 CarryRisk">{stability_gauge}</div>
      <div class="driver-line">主要缓冲：{html.escape(counter_sources)}</div>
      <div class="stability-note">结构稳定度 = 100 − CarryRisk，仅作反向展示，不是新模型或独立信号</div>
    </article>
  </section>

  <section class="axes-section" aria-labelledby="axes-title">
    <h2 class="section-kicker" id="axes-title">五个状态轴 <small>前四项是风险结构；Repair 单独回答高压后的修复</small></h2>
    <div class="axis-grid">{axis_cards}</div>
  </section>

  <section class="probability-strip" aria-labelledby="probability-summary-title">
    <div class="prob-heading">
      <h2 id="probability-summary-title">概率摘要</h2>
      <p>{html.escape(outlook)}</p>
    </div>
    <div class="prob-summary-grid" style="--summary-count:{summary_count}">{probability_summary}</div>
  </section>

  <div class="actions">
    <button type="button" class="action-button primary" data-open-panel="conflict-panel" aria-controls="conflict-panel" aria-expanded="false">查看冲突依据</button>
    <button type="button" class="action-button" data-open-panel="quant-panel" aria-controls="quant-panel" aria-expanded="false">展开量化详情</button>
  </div>

  <details class="detail-panel" id="conflict-panel">
    <summary>冲突依据：哪些证据在升温，哪些证据仍有缓冲</summary>
    <div class="detail-content">
      <p class="conflict-summary">{html.escape(conflict_summary)}</p>
      <div class="grid evidence-grid">
        <div class="box"><h3>升温 / 风险驱动</h3><ul>{_evidence_html(drivers)}</ul></div>
        <div class="box"><h3>反向 / 缓冲证据</h3><ul>{_evidence_html(counters)}</ul></div>
        <div class="box"><h3>边际修复证据</h3><ul>{_evidence_html(repair_evidence)}</ul></div>
        <div class="box"><h3>结构触发</h3><ul>{_plain_list_html(triggers, empty="当日无结构触发")}</ul></div>
        <div class="box"><h3>什么会改变判断</h3><ul>{_plain_list_html(changes_view, empty="暂无")}</ul></div>
      </div>
    </div>
  </details>

  <details class="detail-panel" id="quant-panel">
    <summary>量化详情：曲线、完整概率、历史路径与原始诊断</summary>
    <div class="detail-content">
      <section class="deep-section"><h2>现在：五个状态答案与五个分数</h2><div class="grid answers">{answer_cards}</div><div class="grid scores">{score_cards}</div></section>
      <section class="deep-section"><h2>期限结构</h2><div class="grid curves"><div class="box">{iv_chart}</div><div class="box">{vx_chart}</div></div></section>
      <section class="deep-section"><h2>证据与改变条件</h2><p class="box">{html.escape(str(story.get('narrative', '')))}</p></section>
      <section class="deep-section"><h2>接下来：四类状态转移概率</h2><div class="grid probs">{probability_cards}</div></section>
      <section class="deep-section"><h2>1 / 5 / 20 日变化</h2>{changes}</section>
      <section class="deep-section"><h2>历史状态路径</h2><div class="box">{history_chart}</div></section>
      <section class="deep-section"><h2>历史概率路径</h2>{probability_history_chart}</section>
      <details class="diagnostics"><summary>十五项原始指标与完整诊断</summary><pre>{html.escape(diagnostics)}</pre></details>
    </div>
  </details>
</main>
{LIVE_STATUS_SCRIPT}
</body></html>"""


def build_dashboard_file(
    snapshot_path: str | Path,
    output_path: str | Path,
    history: pd.DataFrame | None = None,
    oof: pd.DataFrame | None = None,
) -> Path:
    snapshot = read_json(snapshot_path)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_dashboard(snapshot, history, oof), encoding="utf-8")
    return target


def serve_dashboard(
    snapshot_path: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = False,
    history: pd.DataFrame | None = None,
    oof: pd.DataFrame | None = None,
) -> None:
    snapshot = Path(snapshot_path).resolve()
    output_dir = snapshot.parent / ".dashboard"
    index = build_dashboard_file(snapshot, output_dir / "index.html", history, oof)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(index.parent), **kwargs)

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"MatVIX Dashboard: {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

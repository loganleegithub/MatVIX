from __future__ import annotations

import html
import json
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

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
    iv.add_trace(go.Scatter(x=[9, 30, 93, 184], y=iv_values, mode="lines+markers"))
    iv.update_layout(
        title="SPX 隐含波动率目标期限曲线",
        xaxis_title="目标日数",
        yaxis_title="指数点",
        height=330,
        margin=dict(l=45, r=20, t=55, b=45),
    )
    vx_settles = observations.get("vx_settles") or []
    vx_ids = observations.get("vx_contract_ids") or []
    vx = go.Figure()
    vx.add_trace(go.Scatter(x=vx_ids, y=vx_settles, mode="lines+markers"))
    vx.update_layout(
        title="标准月 VX F1–F6 官方结算曲线",
        xaxis_title="合约",
        yaxis_title="VIX 点",
        height=330,
        margin=dict(l=45, r=20, t=55, b=45),
    )
    return (
        pio.to_html(
            iv, full_html=False, include_plotlyjs="inline", config={"displayModeBar": False}
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
    for field, label in (
        ("baseline_score", "Baseline"),
        ("carry_risk_score", "CarryRisk"),
        ("shock_score", "Shock"),
        ("tail_price_score", "TailPrice"),
        ("persistence_score", "Persistence"),
        ("repair_score", "Repair"),
    ):
        if field in frame:
            figure.add_trace(
                go.Scatter(x=frame["session_date"], y=frame[field], mode="lines", name=label)
            )
    figure.update_layout(
        title="过去252个交易日状态分数路径",
        yaxis=dict(range=[0, 100]),
        height=380,
        margin=dict(l=45, r=20, t=55, b=45),
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
        yaxis=dict(tickformat=".0%", range=[0, 1]),
        height=430,
        margin=dict(l=45, r=20, t=55, b=45),
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
    answers = story["answers"]
    scores = story["scores"]
    iv_chart, vx_chart = _curve_html(snapshot)
    score_cards = "".join(
        f'<div class="score-card"><span>{html.escape(SCORE_LABELS[key])}</span><strong>{_fmt_score(value)}</strong></div>'
        for key, value in scores.items()
    )
    answer_cards = "".join(
        f'<div class="answer"><small>{html.escape(key.upper())}</small><b>{html.escape(str(value))}</b></div>'
        for key, value in answers.items()
        if key != "outlook"
    )
    probability_cards = "".join(
        f"""<article class="prob-card">
          <h3>{html.escape(EVENT_LABELS[event_id])}</h3>
          <div class="probability">{html.escape(_fmt_probability(event))}</div>
          <dl><dt>历史基准</dt><dd>{html.escape(_fmt_base(event))}</dd>
              <dt>Uplift</dt><dd>{html.escape(_fmt_uplift(event))}</dd>
              <dt>事件状态</dt><dd>{html.escape(event["event_status"])}</dd>
              <dt>模型</dt><dd>{html.escape(event["model_status"])}</dd>
              <dt>概率类型</dt><dd>{html.escape(event["probability_kind"] or "—")}</dd>
              <dt>有效至</dt><dd>{html.escape(event["valid_through_session"] or "—")}</dd></dl>
          <small>{html.escape(EVENT_DEFINITIONS[event_id])}</small>
          <p>{html.escape(event["interpretation"])}</p>
        </article>"""
        for event_id, event in snapshot["probability_judgment"].items()
    )
    diagnostics = json.dumps(
        {
            "observations": snapshot.get("observations", {}),
            "diagnostics": snapshot.get("diagnostics", {}),
        },
        ensure_ascii=False,
        indent=2,
    )
    changes = _change_table(snapshot, history)
    history_chart = _history_chart(history, snapshot["session_date"])
    probability_history_chart = _probability_history_chart(oof, snapshot["session_date"])
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MatVIX {html.escape(snapshot["session_date"])}</title>
<style>
:root{{--bg:#0b1020;--panel:#151c30;--panel2:#1b2540;--text:#eef2ff;--muted:#aeb8d0;--line:#2f3a5b;--accent:#75a7ff}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:1280px;margin:auto;padding:28px}} header{{padding:28px;border:1px solid var(--line);border-radius:18px;background:linear-gradient(135deg,#17213b,#10172a)}}
h1{{font-size:30px;margin:0 0 6px}} .meta{{color:var(--muted)}} section{{margin-top:22px}} h2{{font-size:18px;margin:0 0 12px}} .grid{{display:grid;gap:14px}} .scores{{grid-template-columns:repeat(5,1fr)}}
.score-card,.answer,.prob-card,.box{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}} .score-card span,.answer small{{display:block;color:var(--muted)}} .score-card strong{{font-size:28px}} .answers{{grid-template-columns:repeat(5,1fr);margin-top:12px}}
.answer b{{font-size:15px}} .curves{{grid-template-columns:1fr 1fr}} .evidence-grid{{grid-template-columns:1fr 1fr 1fr}} ul{{margin:0;padding-left:20px}} li{{margin:0 0 10px}}
.probs{{grid-template-columns:repeat(4,1fr)}} .probability{{font-size:27px;font-weight:760;margin:10px 0}} dl{{display:grid;grid-template-columns:1fr 1fr;margin:0}} dt{{color:var(--muted)}} dd{{text-align:right;margin:0}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border-radius:12px;overflow:hidden}} th,td{{padding:10px 12px;border-bottom:1px solid var(--line);text-align:right}} th:first-child,td:first-child{{text-align:left}}
details{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}} pre{{white-space:pre-wrap;overflow:auto;color:#d6def4}} .badge{{display:inline-block;padding:3px 8px;border:1px solid var(--line);border-radius:999px;color:var(--muted)}}
@media(max-width:900px){{.scores,.answers,.probs,.curves,.evidence-grid{{grid-template-columns:1fr 1fr}}}} @media(max-width:600px){{.scores,.answers,.probs,.curves,.evidence-grid{{grid-template-columns:1fr}}main{{padding:14px}}}}
</style></head><body><main>
<header><div class="badge">{html.escape(snapshot["data_status"])}</div><h1>{html.escape(story["headline"])}</h1><div class="meta">{html.escape(snapshot["session_date"])} · {html.escape(story["phase"])} / {html.escape(story["pressure_level"])} / {html.escape(story["direction"])}</div><p>{html.escape(story["narrative"])}</p></header>
<section><h2>现在：五个状态答案与五个分数</h2><div class="grid scores">{score_cards}</div><div class="grid answers">{answer_cards}</div></section>
<section><h2>期限结构</h2><div class="grid curves"><div class="box">{iv_chart}</div><div class="box">{vx_chart}</div></div></section>
<section><h2>证据与改变条件</h2><div class="grid evidence-grid"><div class="box"><h3>主要驱动</h3><ul>{_evidence_html(story["drivers"])}</ul></div><div class="box"><h3>反向证据</h3><ul>{_evidence_html(story["counter_evidence"])}</ul></div><div class="box"><h3>修复证据</h3><ul>{_evidence_html(story["repair_evidence"])}</ul></div><div class="box"><h3>结构触发</h3><ul>{_plain_list_html(story["structural_triggers"], empty="当日无结构触发")}</ul></div><div class="box"><h3>什么会改变判断</h3><ul>{_plain_list_html(story["what_changes_the_view"], empty="暂无")}</ul></div></div></section>
<section><h2>接下来：四类状态转移概率</h2><div class="grid probs">{probability_cards}</div></section>
<section><h2>1 / 5 / 20 日变化</h2>{changes}</section>
<section><h2>历史状态路径</h2><div class="box">{history_chart}</div></section>
<section><h2>历史概率路径</h2>{probability_history_chart}</section>
<section><details><summary>十五项原始指标与完整诊断</summary><pre>{html.escape(diagnostics)}</pre></details></section>
</main></body></html>"""


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

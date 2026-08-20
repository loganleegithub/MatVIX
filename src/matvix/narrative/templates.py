from __future__ import annotations

from typing import Any

import pandas as pd

from matvix.constants import EVENT_ORDER
from matvix.narrative.drivers import rank_evidence, structural_triggers

PHASE_HEADLINES = {
    "UNKNOWN": "今日核心数据不足，暂不形成完整市场天气。",
    "ACUTE_FRONT_STRESS": "前端保险市场进入急性压力。",
    "REPAIR_IN_PROGRESS": "高压后的修复阶段仍在进行。",
    "BROAD_PERSISTENT_STRESS": "压力已扩散并形成持续性高压。",
    "CALENDAR_LOCALIZED_PREMIUM": "保险溢价集中在已知日历窗口附近。",
    "PRESSURE_BUILDING": "保险市场压力正在累积。",
    "TAIL_RICH_QUIET_CURVE": "表面曲线平静，但下行尾部风险中性定价偏贵。",
    "CARRY_SUPPORTIVE_LOW_STRESS": "前端 carry 条件健康，短端压力较低。",
    "MIXED_TRANSITION": "市场证据分化，处于过渡状态。",
}

AXIS_SENTENCES = {
    "carry": {
        "SUPPORTIVE": "前端曲线与基差仍支持 carry 环境。",
        "MIXED": "前端曲线与基差给出混合信号，carry 条件并不清晰。",
        "STRESSED": "前端 carry 结构正在受损，承担波动率卖方风险的环境变差。",
        "INVERTED": "前端 VIX 期货已经倒挂，carry 环境明显受损。",
        "UNKNOWN": "当前无法形成完整的 carry 判断。",
    },
    "shock": {
        "CALM": "短期限保险价格暂未出现异常加速。",
        "BUILDING": "短期限保险定价开始升温，但尚未构成急性压力。",
        "HIGH": "短期限保险正在快速重定价，前端压力较高。",
        "ACUTE": "多个前端结构同时确认急性压力。",
        "UNKNOWN": "当前无法形成完整的急性重定价判断。",
    },
    "tail": {
        "NORMAL": "下行尾部相对中心的风险中性定价处于自身正常区间。",
        "ELEVATED": "下行尾部相对中心的风险中性定价开始突出。",
        "RICH": "下行尾部相对中心的风险中性定价偏贵，即使现货波动率尚未极端也需关注。",
        "EXTREME": "下行尾部相对中心的风险中性定价处于自身历史极端区间。",
        "UNKNOWN": "当前无法形成完整的尾部定价判断。",
    },
    "persistence": {
        "NORMAL": "中长期期限尚未显示压力扩散。",
        "FRONT_LOCALIZED": "压力主要集中在前端，尚未确认向中期限扩散。",
        "DIFFUSING": "中期限 forward volatility 正在上升，压力出现扩散证据。",
        "PERSISTENT": "中期限压力已连续维持，当前更接近持续性高压环境。",
        "MIXED": "期限广度证据相互冲突，暂不能归为局部或持续扩散。",
        "UNKNOWN": "当前无法形成完整的期限广度判断。",
    },
    "repair": {
        "INACTIVE": "当前没有足够的同步修复证据。",
        "BUILDING": "多项边际修复信号正在形成，但尚未完成确认。",
        "CONFIRMED": "多项边际修复证据占优，但这不代表绝对风险已经回到低位。",
        "UNKNOWN": "当前无法形成完整的修复判断。",
    },
}

CHANGES = {
    "UNKNOWN": ["data_status=OK 后按历史前态顺序重算"],
    "ACUTE_FRONT_STRESS": ["hard_acute=false 且 Shock<75 连续两日"],
    "REPAIR_IN_PROGRESS": ["hard_acute=true", "Repair<60 连续两日"],
    "BROAD_PERSISTENT_STRESS": ["persistent_now=false", "repair_answer=CONFIRMED"],
    "CALENDAR_LOCALIZED_PREMIUM": ["事件窗口结束", "NearStress<=0", "Persistence>=55"],
    "PRESSURE_BUILDING": ["Shock<55 且 FrontSlope30>0 连续两日"],
    "TAIL_RICH_QUIET_CURVE": ["TailPrice<70", "Shock>=65", "Persistence>=55"],
    "CARRY_SUPPORTIVE_LOW_STRESS": ["FrontSlope30<0", "Shock>=65"],
    "MIXED_TRANSITION": ["任一非 mixed 的 raw phase 连续两日成立"],
}


def what_changes_the_view(phase: str) -> list[str]:
    return CHANGES.get(phase, CHANGES["UNKNOWN"])[:3]


def _outlook_sentence(events: dict[str, dict[str, Any]], outlook: str) -> str:
    if outlook in EVENT_ORDER:
        return f"相对历史基准提升最明显的是 {outlook}。"
    if outlook == "NO_STRONG_EDGE":
        return "当前四类转移概率均未明显偏离各自历史基准。"
    if outlook == "BASE_RATE_ONLY":
        return "当前仅有同类历史发生率，特征尚未提供可信增量判断。"
    if outlook == "NOT_APPLICABLE":
        return "当前四类转移问题均不适用于已有状态。"
    return "当前没有可发布的状态转移概率判断。"


def basis30_market_story(row: pd.Series) -> str | None:
    """Explain the five-session basis move through spot and 30-day futures legs."""
    fields = ("d5_log_vxcm30", "d5_log_vix", "d5_basis30_eod")
    if any(pd.isna(row.get(field)) for field in fields):
        return None

    vx_change = float(row["d5_log_vxcm30"])
    vix_change = float(row["d5_log_vix"])
    basis_change = float(row["d5_basis30_eod"])
    if basis_change > 0:
        if vix_change < 0 and vx_change <= 0:
            return "五日 Basis30EOD 走阔主要伴随现货 VIX 更快回落，反映即期保险压力消退，而不是远期保险价格上冲。"
        if vx_change > 0 and vix_change >= 0:
            return "五日 Basis30EOD 走阔主要伴随 30 日 VX 合成价抬升更快，说明远期保险价格在上移，不能只解读为现货压力修复。"
        if vix_change < 0 < vx_change:
            return "五日 Basis30EOD 走阔同时来自现货 VIX 回落与 30 日 VX 合成价抬升，即期压力消退和远期保险价格上移并存。"
        return "五日 Basis30EOD 走阔，30 日 VX 合成价相对现货 VIX 更强。"
    if basis_change < 0:
        if vix_change > 0 and vx_change >= 0:
            return (
                "五日 Basis30EOD 收窄主要伴随现货 VIX 上升更快，说明即期保险需求正在追赶远期价格。"
            )
        if vx_change < 0 and vix_change <= 0:
            return "五日 Basis30EOD 收窄主要伴随 30 日 VX 合成价回落更快，反映远期保险价格下移，不等同于现货急性升温。"
        if vx_change < 0 < vix_change:
            return "五日 Basis30EOD 收窄同时来自现货 VIX 上升与 30 日 VX 合成价回落，即期压力升温而远期价格下移。"
        return "五日 Basis30EOD 收窄，现货 VIX 相对 30 日 VX 合成价更强。"
    return "五日 Basis30EOD 基本持平，现货 VIX 与 30 日 VX 合成价没有形成新的相对定价变化。"


def build_narrative(
    row: pd.Series,
    *,
    drivers: list[dict[str, Any]],
    counter_evidence: list[dict[str, Any]],
    events: dict[str, dict[str, Any]],
    outlook: str,
) -> str:
    phase = str(row.get("phase", "UNKNOWN"))
    headline = PHASE_HEADLINES.get(phase, PHASE_HEADLINES["UNKNOWN"])
    sentences = [
        headline,
        AXIS_SENTENCES["carry"][str(row.get("carry_answer", "UNKNOWN"))],
        AXIS_SENTENCES["shock"][str(row.get("shock_answer", "UNKNOWN"))]
        + " "
        + AXIS_SENTENCES["persistence"][str(row.get("persistence_answer", "UNKNOWN"))],
        AXIS_SENTENCES["tail"][str(row.get("tail_answer", "UNKNOWN"))]
        + " "
        + AXIS_SENTENCES["repair"][str(row.get("repair_answer", "UNKNOWN"))],
    ]
    candidate = row.get("candidate_phase")
    if candidate is not None and not pd.isna(candidate) and str(candidate) != phase:
        streak = int(row.get("candidate_streak", 0) or 0)
        sentences.insert(
            1,
            f"状态切换仍在确认：当日原始证据指向 {candidate}，已连续 {streak} 日，"
            f"因此发布阶段暂时保留为 {phase}。",
        )
    if (
        pd.notna(row.get("shock_score"))
        and float(row["shock_score"]) >= 85
        and pd.notna(row.get("front_confirmation_count"))
        and float(row["front_confirmation_count"]) < 2
    ):
        sentences.append("价格速度极端，但结构确认不足。")
    if str(row.get("data_status", "UNKNOWN")) == "OK":
        basis_story = basis30_market_story(row)
        if basis_story:
            sentences.append(basis_story)
    if drivers:
        sentences.append("主要证据是" + "；".join(item["meaning"] for item in drivers) + "。")
    else:
        sentences.append("当前没有单项风险贡献超过 75% 历史分位。")
    if counter_evidence:
        sentences.append(
            "反向证据包括" + "；".join(item["meaning"] for item in counter_evidence) + "。"
        )
    if str(row.get("data_status", "UNKNOWN")) == "OK":
        _, _, repair_evidence = rank_evidence(row)
        triggers = structural_triggers(row)
        if repair_evidence:
            sentences.append(
                "边际修复证据包括" + "；".join(item["meaning"] for item in repair_evidence) + "。"
            )
        if triggers:
            sentences.append("当日结构触发包括" + "；".join(triggers) + "。")
    axes = [
        row.get(name)
        for name in ("carry_risk_score", "shock_score", "tail_price_score", "persistence_score")
    ]
    valid_axes = [float(value) for value in axes if value is not None and not pd.isna(value)]
    if len(valid_axes) == 4 and max(valid_axes) - min(valid_axes) >= 40:
        sentences.append("当前证据分化明显，单一方向叙事不足。")
    sentences.append(_outlook_sentence(events, outlook))
    return "".join(sentences)

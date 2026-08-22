from __future__ import annotations

from typing import Any, cast

import pandas as pd

from matvix.state.scores import component_contributions, repair_components

HIGH_MEANINGS = {
    "carry.front_slope": "前端 VX 曲线相对自身历史明显平坦或倒挂",
    "carry.basis30_eod": "官方 EOD 参考基差明显压缩或转负",
    "carry.slope_change_5d": "前端曲线在五日内明显恶化",
    "shock.near_stress": "VIX9D 相对 VIX 明显抬升",
    "shock.vix_change_1d": "VIX 单日重定价速度偏高",
    "shock.vix_change_5d": "VIX 五日累计重定价速度偏高",
    "shock.vvix_change_5d": "vol-of-vol 在五日内明显加速",
    "shock.vvix_level": "VIX 期权隐含波动率处于高位",
    "tail.skew_level": "下行尾部相对中心的风险中性定价更突出",
    "tail.skew_change_5d": "SKEW 五日变化偏强",
    "persistence.f4_f7_level": "F4–F7 平均价格处于历史高位",
    "persistence.f4_f7_slope30": "F4–F7 标准化斜率明显压平或倒挂",
    "persistence.f4_f7_level_change_5d": "F4–F7 平均价格五日明显抬升",
    "persistence.f4_f7_inversion_breadth": "F4–F7 倒挂覆盖更多相邻期限段",
    "repair.vix": "VIX 五日边际回落",
    "repair.near_stress": "VIX9D/VIX 前端压力回落",
    "repair.front_slope": "VX 前端曲线边际恢复",
    "repair.vvix": "vol-of-vol 边际回落",
    "repair.f4_f7_level": "F4–F7 平均价格五日边际回落",
}

LOW_MEANINGS = {
    "carry.front_slope": "前端 VX 曲线仍相对陡峭，carry 结构未明显受损",
    "carry.basis30_eod": "官方 EOD 参考基差仍有缓冲",
    "carry.slope_change_5d": "前端曲线五日内未明显恶化",
    "shock.near_stress": "VIX9D 相对 VIX 尚未明显抬升",
    "shock.vix_change_1d": "VIX 单日重定价速度偏低",
    "shock.vix_change_5d": "VIX 五日累计重定价速度偏低",
    "shock.vvix_change_5d": "vol-of-vol 五日内未明显加速",
    "shock.vvix_level": "VIX 期权隐含波动率尚未处于高位",
    "tail.skew_level": "下行尾部相对中心的风险中性定价并不突出",
    "tail.skew_change_5d": "SKEW 五日变化偏弱",
    "persistence.f4_f7_level": "F4–F7 平均价格尚未处于高位",
    "persistence.f4_f7_slope30": "F4–F7 标准化斜率仍较陡峭",
    "persistence.f4_f7_level_change_5d": "F4–F7 平均价格五日未明显抬升",
    "persistence.f4_f7_inversion_breadth": "F4–F7 倒挂未覆盖更多相邻期限段",
}


def _float_value(value: object) -> float:
    return float(cast(Any, value))


def _evidence(record: dict[str, Any], *, high: bool) -> dict[str, Any]:
    raw = record.get("raw_value")
    percentile = record.get("percentile")
    evidence_id = str(record["id"])
    meaning = (HIGH_MEANINGS if high else LOW_MEANINGS)[evidence_id]
    if evidence_id == "persistence.f4_f7_inversion_breadth" and raw is not None and not pd.isna(raw):
        # F4F7InversionShare is already a normalized three-segment breadth ratio.  It
        # occupies the schema's common 0-1 evidence slot but is not a rolling
        # historical percentile.
        meaning += f"（三个 F4–F7 相邻期限段中的倒挂占比为 {_float_value(raw):.0%}）"
    return {
        "evidence_id": evidence_id,
        "feature": str(record["feature_refs"][0]),
        "raw_value": None if raw is None or pd.isna(raw) else _float_value(raw),
        "percentile": _float_value(percentile),
        "contribution": _float_value(record.get("contribution", 0.0)),
        "meaning": meaning,
    }


def rank_evidence(
    row: pd.Series,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    risk = component_contributions(row)
    drivers = sorted(
        (record for record in risk if _float_value(record["percentile"]) >= 0.75),
        key=lambda record: (-_float_value(record["contribution"]), str(record["id"])),
    )[:3]
    counters = sorted(
        (record for record in risk if _float_value(record["percentile"]) <= 0.35),
        key=lambda record: (_float_value(record["contribution"]), str(record["id"])),
    )[:2]
    repair = sorted(
        (record for record in repair_components(row) if _float_value(record["percentile"]) >= 0.75),
        key=lambda record: (-_float_value(record["contribution"]), str(record["id"])),
    )[:3]
    return (
        [_evidence(record, high=True) for record in drivers],
        [_evidence(record, high=False) for record in counters],
        [_evidence(record, high=True) for record in repair],
    )


def structural_triggers(row: pd.Series) -> list[str]:
    triggers: list[str] = []
    for condition, text in (
        (
            pd.notna(row.get("vix9d_close"))
            and pd.notna(row.get("vix_close"))
            and float(row["vix9d_close"]) > float(row["vix_close"]),
            "VIX9D 高于 VIX",
        ),
        (
            pd.notna(row.get("ts12")) and float(row["ts12"]) < 0,
            "VX F1 高于 F2，前端倒挂",
        ),
        (
            pd.notna(row.get("p_cash_vix_oscillator"))
            and float(row["p_cash_vix_oscillator"]) >= 0.90,
            "Cash VIX Oscillator 处于至少 90% 历史分位",
        ),
        (
            bool(row.get("hard_acute")) if pd.notna(row.get("hard_acute")) else False,
            "急性硬确认成立",
        ),
    ):
        if condition:
            triggers.append(text)
    return triggers

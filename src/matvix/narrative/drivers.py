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
    "persistence.fvol_30_93": "30–93 日 forward volatility 处于高位",
    "persistence.fvol_93_184": "93–184 日 forward volatility 处于高位",
    "persistence.fvol_change_5d": "中期限 forward volatility 正在扩散",
    "persistence.curve_breadth": "VX 倒挂已覆盖更多连续期限段",
    "repair.vix": "VIX 五日边际回落",
    "repair.near_stress": "VIX9D/VIX 前端压力回落",
    "repair.front_slope": "VX 前端曲线边际恢复",
    "repair.vvix": "vol-of-vol 边际回落",
    "repair.fvol_30_93": "中期限 forward volatility 边际回落",
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
    "persistence.fvol_30_93": "30–93 日 forward volatility 尚未抬升",
    "persistence.fvol_93_184": "93–184 日 forward volatility 尚未抬升",
    "persistence.fvol_change_5d": "中期限 forward volatility 尚未出现扩散",
    "persistence.curve_breadth": "VX 倒挂未沿连续期限段扩散",
}


def _float_value(value: object) -> float:
    return float(cast(Any, value))


def _evidence(record: dict[str, Any], *, high: bool) -> dict[str, Any]:
    raw = record.get("raw_value")
    percentile = record.get("percentile")
    evidence_id = str(record["id"])
    meaning = (HIGH_MEANINGS if high else LOW_MEANINGS)[evidence_id]
    if evidence_id == "persistence.curve_breadth" and raw is not None and not pd.isna(raw):
        # CurveInversionShare is already a normalized F1-F6 breadth ratio.  It
        # occupies the schema's common 0-1 evidence slot but is not a rolling
        # historical percentile.
        meaning += f"（五个相邻期限段中的倒挂占比为 {_float_value(raw):.0%}）"
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

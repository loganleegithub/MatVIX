from __future__ import annotations

from enum import StrEnum

SCHEMA_VERSION = "3.0.0"
MODEL_ID = "MATVIX_CBOE_CORE_V3"
FEATURE_VERSION = "3.0.0"
STATE_VERSION = "3.0.0"
PROBABILITY_VERSION = "3.0.0"


class VintageKind(StrEnum):
    OBSERVED_PIT = "OBSERVED_PIT"
    ASSUMED_PIT = "ASSUMED_PIT"
    PROVIDER_BACKTESTED = "PROVIDER_BACKTESTED"


class DataStatus(StrEnum):
    OK = "OK"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


FORMAL_VINTAGES = {VintageKind.OBSERVED_PIT.value, VintageKind.ASSUMED_PIT.value}
VINTAGE_RANK = {
    VintageKind.OBSERVED_PIT.value: 2,
    VintageKind.ASSUMED_PIT.value: 1,
    VintageKind.PROVIDER_BACKTESTED.value: 0,
}

EVENT_HORIZONS = {
    "acute_front_stress_5d": 5,
    "front_inversion_5d": 5,
    "mid_curve_pressure_accelerates_5d": 5,
    "broad_stress_persists_10d": 10,
    "carry_environment_recovers_10d": 10,
}
EVENT_ORDER = tuple(EVENT_HORIZONS)

LOGISTIC_FEATURES = {
    "acute_front_stress_5d": [
        "carry_risk_scaled",
        "shock_scaled",
        "tail_price_scaled",
        "persistence_scaled",
        "score_change5_scaled",
        "front_confirmation_scaled",
    ],
    "front_inversion_5d": [
        "p_neg_front_slope30",
        "p_neg_d5_front_slope30",
        "p_neg_basis30_eod",
        "shock_scaled",
    ],
    "mid_curve_pressure_accelerates_5d": [
        "p_f4_f7_level",
        "p_d5_log_f4_f7_level",
        "p_neg_d5_f4_f7_slope30",
        "f4_f7_inversion_share",
        "shock_scaled",
        "score_change5_scaled",
    ],
    "broad_stress_persists_10d": [
    ],
    "carry_environment_recovers_10d": [
        "repair_scaled",
        "p_d5_front_slope30",
        "p_neg_d5_near_stress",
        "p_d5_f4_f7_slope30",
        "p_neg_d5_log_f4_f7_level",
        "shock_scaled",
    ],
}

BASE_RATE_ONLY_EVENTS = ("broad_stress_persists_10d",)
FEATURE_CONDITIONAL_EVENTS = tuple(
    event for event in EVENT_ORDER if event not in BASE_RATE_ONLY_EVENTS
)

from __future__ import annotations

from enum import StrEnum

SCHEMA_VERSION = "1.0.0"
MODEL_ID = "MATVIX_CBOE_CORE_V1"
FEATURE_VERSION = "1.0.0"
STATE_VERSION = "1.0.0"
PROBABILITY_VERSION = "1.1.0"


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
    "broad_persistent_stress_20d": 20,
    "fast_repair_5d": 5,
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
    "broad_persistent_stress_20d": [
        "persistence_scaled",
        "shock_scaled",
        "tail_price_scaled",
        "p_d5_fvol_30_93",
        "p_fvol_93_184",
        "score_change5_scaled",
    ],
    "fast_repair_5d": [
        "repair_scaled",
        "inverse_score_change5_scaled",
        "p_neg_d5_near_stress",
        "p_d5_front_slope30",
        "shock_scaled",
        "persistence_scaled",
    ],
}

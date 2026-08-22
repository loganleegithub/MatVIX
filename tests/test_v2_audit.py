from __future__ import annotations

import numpy as np
import pandas as pd
from conftest import make_curve

from matvix.v2_audit import _candidate_event_summary, curve_audit_record


def test_curve_audit_distinguishes_direct_and_bounded_30_day_values() -> None:
    session = pd.Timestamp("2025-01-02")
    direct_curve = make_curve(
        session,
        settles=(18, 19, 20, 21, 22, 23, 24),
        days=(10, 40, 70, 100, 130, 160, 190),
    )
    direct = curve_audit_record(direct_curve, session)
    assert direct["f1_f7_count"] == 7
    assert direct["f1_f7_sequential"] is True
    assert direct["strict_vxcm30"] == 18 + (19 - 18) * (30 - 10) / (40 - 10)
    assert np.isnan(direct["bounded_vxcm30_candidate"])

    post_roll_curve = make_curve(
        session,
        settles=(19, 20, 21, 22, 23, 24, 25),
        days=(34, 64, 94, 124, 154, 184, 214),
    )
    post_roll = curve_audit_record(post_roll_curve, session)
    assert np.isnan(post_roll["strict_vxcm30"])
    assert post_roll["bounded_vxcm30_candidate"] == 19 + (20 - 19) * (30 - 34) / (64 - 34)


def test_candidate_event_summary_keeps_incomplete_tail_censored() -> None:
    ledger = pd.DataFrame({"session_date": pd.bdate_range("2021-12-20", periods=20, freq="B")})
    onset = pd.Series(False, index=ledger.index, dtype="boolean")
    onset.loc[[0, 10, 18]] = True
    predicate = pd.Series(False, index=ledger.index, dtype="boolean")
    predicate.loc[[3, 14]] = True

    summary = _candidate_event_summary(
        ledger,
        onset=onset,
        predicate=predicate,
        horizon=5,
    )

    assert summary["overall"] == {
        "eligible": 3,
        "completed": 2,
        "positive": 2,
        "negative": 0,
        "base_rate": 1.0,
        "positive_clusters": 2,
        "model_sample_gate": False,
    }

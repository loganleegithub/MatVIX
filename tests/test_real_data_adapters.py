from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from matvix.data.cboe import import_cboe_history
from matvix.data.cfe import import_cfe_directory, parse_monthly_contract
from matvix.data.spx import import_spx_close


def test_cboe_vix_ohlc_adapter(tmp_path: Path) -> None:
    path = tmp_path / "VIX_History.csv"
    path.write_text("DATE,OPEN,HIGH,LOW,CLOSE\n01/02/2025,17,19,16,18\n", encoding="utf-8")
    frame = import_cboe_history(path, "VIX", datetime(2025, 1, 3, tzinfo=UTC))
    assert set(frame["series_id"]) == {"VIX_OPEN", "VIX_HIGH", "VIX_LOW", "VIX_CLOSE"}
    assert set(frame["vintage_kind"]) == {"ASSUMED_PIT"}
    required = {
        "series_id",
        "session_date",
        "value",
        "unit",
        "source",
        "source_symbol",
        "observed_at",
        "available_at",
        "ingested_at",
        "revision_id",
        "methodology_version",
        "vintage_kind",
    }
    assert required.issubset(frame.columns)


def test_cboe_single_value_adapter(tmp_path: Path) -> None:
    path = tmp_path / "SKEW_History.csv"
    path.write_text("DATE,SKEW\n01/02/2025,140.5\n", encoding="utf-8")
    frame = import_cboe_history(path, "SKEW")
    assert frame.iloc[0]["series_id"] == "SKEW_CLOSE"
    assert frame.iloc[0]["value"] == 140.5


def test_cboe_revision_id_is_stable_per_unchanged_row(tmp_path: Path) -> None:
    path = tmp_path / "SKEW_History.csv"
    path.write_text("DATE,SKEW\n01/02/2025,140.5\n", encoding="utf-8")
    first = import_cboe_history(path, "SKEW")
    path.write_text("DATE,SKEW\n01/02/2025,140.5\n01/03/2025,141.0\n", encoding="utf-8")
    second = import_cboe_history(path, "SKEW")

    assert first.iloc[0]["revision_id"] == second.iloc[0]["revision_id"]


def test_cboe_revision_id_changes_when_row_value_is_revised(tmp_path: Path) -> None:
    path = tmp_path / "SKEW_History.csv"
    path.write_text("DATE,SKEW\n01/02/2025,140.5\n", encoding="utf-8")
    first = import_cboe_history(path, "SKEW")
    path.write_text("DATE,SKEW\n01/02/2025,141.5\n", encoding="utf-8")
    revised = import_cboe_history(path, "SKEW")

    assert first.iloc[0]["revision_id"] != revised.iloc[0]["revision_id"]


def test_spx_authorized_import(tmp_path: Path) -> None:
    path = tmp_path / "spx.csv"
    path.write_text("DATE,CLOSE\n2025-01-02,5900\n", encoding="utf-8")
    frame = import_spx_close(path, source="LICENSED_TEST")
    assert frame.iloc[0]["series_id"] == "SPX_CLOSE"
    assert frame.iloc[0]["source"] == "LICENSED_TEST"


def test_spx_fred_csv_import_and_missing_marker(tmp_path: Path) -> None:
    path = tmp_path / "SP500.csv"
    path.write_text(
        "observation_date,SP500\n2025-01-02,5900.00\n2025-01-03,.\n",
        encoding="utf-8",
    )

    frame = import_spx_close(path)

    assert len(frame) == 1
    assert frame.iloc[0]["value"] == 5900.0
    assert frame.iloc[0]["source"] == "FRED"
    assert frame.iloc[0]["source_symbol"] == "SP500"


def test_cfe_parser_rejects_nonstandard_filename(tmp_path: Path) -> None:
    path = tmp_path / "VX_2025-01-15.csv"  # Jan 2025 standard VX settled Jan 22.
    path.write_text("Trade Date,Futures,Settle\n2025-01-02,VX/F5,18.0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="standard monthly"):
        parse_monthly_contract(path)


def test_cfe_parser_standard_contract(tmp_path: Path) -> None:
    path = tmp_path / "VX_2025-01-22.csv"
    path.write_text("Trade Date,Futures,Settle\n2025-01-02,VX/F5,18.0\n", encoding="utf-8")
    frame = parse_monthly_contract(path)
    assert frame.iloc[0]["contract_id"] == "VX/F5"
    assert frame.iloc[0]["is_standard_monthly"]
    assert frame.iloc[0]["vintage_kind"] == "ASSUMED_PIT"


def test_cfe_parser_excludes_nonpositive_settlement(tmp_path: Path) -> None:
    path = tmp_path / "VX_2025-01-22.csv"
    path.write_text("Trade Date,Futures,Settle\n2025-01-02,VX/F5,0\n", encoding="utf-8")

    frame = parse_monthly_contract(path)

    assert frame.empty


def test_cfe_directory_does_not_silently_skip_malformed_standard_file(tmp_path: Path) -> None:
    path = tmp_path / "VX_2025-01-22.csv"
    path.write_text("Trade Date,Futures\n2025-01-02,VX/F5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing CFE columns"):
        import_cfe_directory(tmp_path)

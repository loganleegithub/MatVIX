from __future__ import annotations

import errno
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from matvix.constants import EVENT_ORDER, MODEL_ID
from matvix.daily_update import frame_content_digest, with_snapshot_publication_binding
from matvix.http_runtime import (
    DashboardHTTPRuntime,
    find_latest_accepted_snapshot,
    inject_runtime_polling,
)
from matvix.storage import read_json, read_parquet, write_json, write_parquet


def _publish(
    project: Path,
    session: str,
    *,
    passed: bool = True,
    data_status: str = "OK",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model_id": MODEL_ID,
        "session_date": session,
        "decision_as_of": f"{session}T09:20:00-04:00",
        "data_status": data_status,
        "market_story": {"headline": f"session {session}"},
        "probability_judgment": {
            event: {
                "event_status": "NOT_APPLICABLE",
                "model_status": "NOT_RUN",
                "probability_kind": None,
            }
            for event in EVENT_ORDER
        },
    }
    snapshot_path = project / "outputs" / "daily" / f"{session}.json"
    write_json(payload, snapshot_path)
    write_json(
        with_snapshot_publication_binding(
            {"session_date": session, "passed": passed},
            snapshot_path,
        ),
        project / "artifacts" / "acceptance" / f"real_acceptance_{session}.json",
    )
    return payload


def _renderer(
    payload: dict[str, Any],
    _history: pd.DataFrame | None,
    _oof: pd.DataFrame | None,
) -> str:
    session = payload["session_date"]
    return f"<!doctype html><html><body><main>{session}</main></body></html>"


def _request(
    runtime: DashboardHTTPRuntime,
    path: str,
    *,
    method: str = "GET",
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(runtime.url.rstrip("/") + path, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _json_request(runtime: DashboardHTTPRuntime, path: str) -> dict[str, Any]:
    status, _, body = _request(runtime, path)
    assert status == 200
    loaded = json.loads(body)
    assert isinstance(loaded, dict)
    return loaded


def test_latest_snapshot_requires_passing_receipt_and_ok_data(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-18")
    _publish(tmp_path, "2026-08-19", passed=False)
    _publish(tmp_path, "2026-08-20", data_status="UNKNOWN")
    write_json(
        {"session_date": "2026-08-21", "data_status": "OK"},
        tmp_path / "outputs" / "daily" / "2026-08-21.json",
    )
    write_json(
        {"session_date": "../../unsafe", "passed": True},
        tmp_path / "artifacts" / "acceptance" / "real_acceptance_unsafe.json",
    )

    latest = find_latest_accepted_snapshot(tmp_path)

    assert latest is not None
    assert latest.session_date == "2026-08-18"
    assert latest.payload["data_status"] == "OK"


def test_each_candidate_uses_its_own_receipt_binding(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-19")
    _publish(tmp_path, "2026-08-18")

    latest = find_latest_accepted_snapshot(tmp_path)

    assert latest is not None
    assert latest.session_date == "2026-08-19"


@pytest.mark.parametrize("damaged_file", ["snapshot", "receipt"])
def test_corrupt_newest_publication_falls_back_to_last_good(
    tmp_path: Path,
    damaged_file: str,
) -> None:
    _publish(tmp_path, "2026-08-18")
    _publish(tmp_path, "2026-08-19")
    damaged_path = (
        tmp_path / "outputs" / "daily" / "2026-08-19.json"
        if damaged_file == "snapshot"
        else tmp_path / "artifacts" / "acceptance" / "real_acceptance_2026-08-19.json"
    )
    damaged_path.write_bytes(b'{"session_date":')

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=_renderer) as runtime:
        status = _json_request(runtime, "/api/status")
        snapshot = _json_request(runtime, "/api/snapshot")

    assert status["runtime_status"] == "RUNNING"
    assert status["last_good_session"] == "2026-08-18"
    assert snapshot["session_date"] == "2026-08-18"


def test_touched_old_receipt_cannot_authorize_replaced_snapshot(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-18")
    _publish(tmp_path, "2026-08-19")
    snapshot_path = tmp_path / "outputs" / "daily" / "2026-08-19.json"
    receipt_path = tmp_path / "artifacts" / "acceptance" / "real_acceptance_2026-08-19.json"
    replacement = {
        "session_date": "2026-08-19",
        "data_status": "OK",
        "market_story": {"headline": "replacement generation"},
    }
    write_json(replacement, snapshot_path)
    touched = snapshot_path.stat().st_mtime_ns + 1_000_000
    os.utime(receipt_path, ns=(touched, touched))

    latest = find_latest_accepted_snapshot(tmp_path)

    assert receipt_path.stat().st_mtime_ns > snapshot_path.stat().st_mtime_ns
    assert latest is not None
    assert latest.session_date == "2026-08-18"


def test_legacy_unbound_receipt_is_not_a_formal_publication(tmp_path: Path) -> None:
    session = "2026-08-18"
    write_json(
        {"session_date": session, "data_status": "OK"},
        tmp_path / "outputs" / "daily" / f"{session}.json",
    )
    write_json(
        {"session_date": session, "passed": True},
        tmp_path / "artifacts" / "acceptance" / f"real_acceptance_{session}.json",
    )

    assert find_latest_accepted_snapshot(tmp_path) is None


def test_runtime_serves_html_status_snapshot_and_health(tmp_path: Path) -> None:
    expected = _publish(tmp_path, "2026-08-18")
    write_json(
        {
            "status": "WAITING_FOR_SOURCE",
            "updated_at": "2026-08-20T13:25:00+00:00",
            "latest_complete_session": "2026-08-18",
            "next_check_at": "2026-08-20T13:40:00+00:00",
            "sources": {
                "CBOE_VIX": {"latest_session": "2026-08-19", "status": "READY"},
                "CFE_VX": {"latest_session": "2026-08-18", "status": "WAITING"},
            },
        },
        tmp_path / "outputs" / "runtime" / "update_status.json",
    )

    with DashboardHTTPRuntime(
        tmp_path,
        port=0,
        renderer=_renderer,
        poll_interval_seconds=0.01,
    ) as runtime:
        status_code, headers, body = _request(runtime, "/")
        assert status_code == 200
        assert headers["Cache-Control"] == "no-store"
        document = body.decode()
        assert "2026-08-18" in document
        assert 'id="matvix-runtime-poll"' in document
        assert 'data-dashboard-revision="2026-08-18:' in document
        assert "fetch('/api/status'" in document

        status = _json_request(runtime, "/api/status")
        assert status["runtime_status"] == "RUNNING"
        assert status["product_status"] == "READY"
        assert status["product_status_reasons"] == []
        assert status["trading_authorized"] is False
        assert set(status["event_models"]) == set(EVENT_ORDER)
        assert status["snapshot_freshness"]["session_date"] == "2026-08-18"
        assert status["latest_session"] == "2026-08-18"
        assert status["latest_snapshot_session"] == "2026-08-18"
        assert status["last_good_session"] == "2026-08-18"
        assert status["dashboard_revision"].startswith("2026-08-18:")
        assert status["publication_date"] == "2026-08-18"
        assert status["last_update_at"] == "2026-08-20T13:25:00+00:00"
        assert status["data_sources"]["CFE_VX"]["status"] == "WAITING"
        assert status["update"]["next_check_at"] == "2026-08-20T13:40:00+00:00"

        snapshot = _json_request(runtime, "/api/snapshot")
        assert snapshot == expected

        health = _json_request(runtime, "/healthz")
        assert health["ok"] is True
        assert health["latest_session"] == "2026-08-18"


def test_cold_start_never_renders_with_mutated_unaccepted_history_sidecars(
    tmp_path: Path,
) -> None:
    session = "2026-08-18"
    _publish(tmp_path, session)
    states_path = tmp_path / "data" / "processed" / "states.parquet"
    oof_path = tmp_path / "data" / "probability" / "oof_ledger.parquet"
    write_parquet(
        pd.DataFrame([{"session_date": session, "generation": "accepted"}]),
        states_path,
    )
    write_parquet(
        pd.DataFrame([{"prediction_date": session, "generation": "accepted"}]),
        oof_path,
    )
    receipt_path = (
        tmp_path / "artifacts" / "acceptance" / f"real_acceptance_{session}.json"
    )
    receipt = read_json(receipt_path)
    receipt["release_contract"] = {
        "dashboard_state_history_digest": frame_content_digest(read_parquet(states_path)),
        "dashboard_oof_digest": frame_content_digest(read_parquet(oof_path)),
    }
    write_json(receipt, receipt_path)

    accepted_inputs: list[tuple[pd.DataFrame | None, pd.DataFrame | None]] = []

    def capture_accepted(
        payload: dict[str, Any],
        history: pd.DataFrame | None,
        oof: pd.DataFrame | None,
    ) -> str:
        accepted_inputs.append((history, oof))
        return f"<html><body>{payload['session_date']}</body></html>"

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=capture_accepted) as runtime:
        assert _request(runtime, "/")[0] == 200
    assert accepted_inputs[0][0] is not None and accepted_inputs[0][1] is not None

    write_parquet(
        pd.DataFrame([{"session_date": session, "generation": "failed-candidate"}]),
        states_path,
    )
    mutated_inputs: list[tuple[pd.DataFrame | None, pd.DataFrame | None]] = []

    def capture_mutated(
        payload: dict[str, Any],
        history: pd.DataFrame | None,
        oof: pd.DataFrame | None,
    ) -> str:
        mutated_inputs.append((history, oof))
        return f"<html><body>{payload['session_date']}</body></html>"

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=capture_mutated) as runtime:
        assert _request(runtime, "/")[0] == 200
    assert mutated_inputs == [(None, None)]


def test_failed_candidate_sidecars_cannot_change_frozen_trader_evidence(
    tmp_path: Path,
) -> None:
    session = "2026-08-18"
    payload: dict[str, Any] = {
        "session_date": session,
        "decision_as_of": "2026-08-19T09:20:00-04:00",
        "data_status": "OK",
        "market_story": {
            "headline": "证据分化",
            "phase": "MIXED_TRANSITION",
            "pressure_level": "WATCH",
            "direction": "RISING",
            "baseline_score": 40.0,
            "answers": {
                "carry": "SUPPORTIVE",
                "shock": "BUILDING",
                "tail": "NORMAL",
                "persistence": "MIXED",
                "repair": "INACTIVE",
                "outlook": "NO_STRONG_EDGE",
            },
            "scores": {
                "carry_risk": 8.0,
                "shock": 50.0,
                "tail_price": 58.0,
                "persistence": 56.0,
                "repair": 45.0,
            },
            "drivers": [],
            "counter_evidence": [],
            "repair_evidence": [],
            "structural_triggers": [],
            "what_changes_the_view": [],
            "narrative": "证据分化",
        },
        "probability_judgment": {},
        "observations": {},
        "diagnostics": {
            "hard_acute": False,
            "component_contributions": [
                {
                    "axis": "shock",
                    "id": "shock.vix_change_1d",
                    "percentile": 0.9,
                    "contribution": 0.05,
                    "feature_refs": ["d1_log_vix"],
                },
                {
                    "axis": "carry_risk",
                    "id": "carry.front_slope",
                    "percentile": 0.1,
                    "contribution": 0.01,
                    "feature_refs": ["front_slope30"],
                },
            ],
        },
    }
    snapshot_path = tmp_path / "outputs" / "daily" / f"{session}.json"
    write_json(payload, snapshot_path)
    states_path = tmp_path / "data" / "processed" / "states.parquet"
    oof_path = tmp_path / "data" / "probability" / "oof_ledger.parquet"
    write_parquet(pd.DataFrame([{"session_date": session, "generation": "accepted"}]), states_path)
    write_parquet(pd.DataFrame([{"prediction_date": session}]), oof_path)
    receipt = with_snapshot_publication_binding(
        {"session_date": session, "passed": True},
        snapshot_path,
    )
    receipt["release_contract"] = {
        "dashboard_state_history_digest": frame_content_digest(read_parquet(states_path)),
        "dashboard_oof_digest": frame_content_digest(read_parquet(oof_path)),
    }
    write_json(
        receipt,
        tmp_path / "artifacts" / "acceptance" / f"real_acceptance_{session}.json",
    )

    # A later failed candidate has overwritten the mutable global sidecar, but
    # has no passing receipt.  A cold-start HTTP renderer must remain on the
    # accepted snapshot's frozen evidence instead of mixing generations.
    write_parquet(
        pd.DataFrame([{"session_date": session, "generation": "failed-candidate"}]),
        states_path,
    )

    with DashboardHTTPRuntime(tmp_path, port=0) as runtime:
        status, _, body = _request(runtime, "/")

    document = body.decode()
    assert status == 200
    assert "主要驱动：VIX" in document
    assert "主要缓冲：VX 曲线" in document
    assert "Shock 分量未进入全局证据榜" not in document
    assert "Carry 分量未进入全局证据榜" not in document


def test_running_service_switches_to_new_accepted_session_without_restart(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-18")
    rendered: list[str] = []

    def renderer(
        payload: dict[str, Any],
        _history: pd.DataFrame | None,
        _oof: pd.DataFrame | None,
    ) -> str:
        session = str(payload["session_date"])
        rendered.append(session)
        return f"<html><body>{session}</body></html>"

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=renderer) as runtime:
        first = _request(runtime, "/")[2].decode()
        assert "2026-08-18" in first

        expected = _publish(tmp_path, "2026-08-19")

        second = _request(runtime, "/")[2].decode()
        assert "2026-08-19" in second
        assert _json_request(runtime, "/api/snapshot") == expected
        assert _json_request(runtime, "/api/status")["latest_session"] == "2026-08-19"

    assert rendered == ["2026-08-18", "2026-08-19"]


def test_render_failure_keeps_last_rendered_good_until_candidate_succeeds(
    tmp_path: Path,
) -> None:
    _publish(tmp_path, "2026-08-18")
    allow_candidate = False

    def renderer(
        payload: dict[str, Any],
        _history: pd.DataFrame | None,
        _oof: pd.DataFrame | None,
    ) -> str:
        if payload["session_date"] == "2026-08-19" and not allow_candidate:
            raise ValueError("candidate render is invalid")
        return f"<html><body>{payload['session_date']}</body></html>"

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=renderer) as runtime:
        assert "2026-08-18" in _request(runtime, "/")[2].decode()
        _publish(tmp_path, "2026-08-19")

        assert "2026-08-18" in _request(runtime, "/")[2].decode()
        failed = _json_request(runtime, "/api/status")
        assert failed["runtime_status"] == "DASHBOARD_RENDER_FAILED"
        assert failed["candidate_session"] == "2026-08-19"
        assert failed["latest_session"] == "2026-08-18"
        assert failed["dashboard_error"]["error_type"] == "ValueError"
        assert _json_request(runtime, "/api/snapshot")["session_date"] == "2026-08-18"

        allow_candidate = True
        recovered = _json_request(runtime, "/api/status")
        assert recovered["runtime_status"] == "RUNNING"
        assert recovered["candidate_session"] is None
        assert recovered["latest_session"] == "2026-08-19"
        assert _json_request(runtime, "/api/snapshot")["session_date"] == "2026-08-19"
        assert "2026-08-19" in _request(runtime, "/")[2].decode()


def test_cold_start_falls_back_to_older_renderable_accepted_snapshot(
    tmp_path: Path,
) -> None:
    _publish(tmp_path, "2026-08-18")
    _publish(tmp_path, "2026-08-19")

    def renderer(
        payload: dict[str, Any],
        _history: pd.DataFrame | None,
        _oof: pd.DataFrame | None,
    ) -> str:
        if payload["session_date"] == "2026-08-19":
            raise ValueError("newest candidate cannot render")
        return f"<html><body>{payload['session_date']}</body></html>"

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=renderer) as runtime:
        status_code, _, body = _request(runtime, "/")
        assert status_code == 200
        assert "2026-08-18" in body.decode()

        status = _json_request(runtime, "/api/status")
        assert status["runtime_status"] == "DASHBOARD_RENDER_FAILED"
        assert status["candidate_session"] == "2026-08-19"
        assert status["latest_session"] == "2026-08-18"
        assert _json_request(runtime, "/api/snapshot")["session_date"] == "2026-08-18"


def test_runtime_is_read_only_and_does_not_serve_arbitrary_files(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-18")
    secret = tmp_path / "secret.txt"
    secret.write_text("not public", encoding="utf-8")

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=_renderer) as runtime:
        assert _request(runtime, "/../secret.txt")[0] == 404
        assert _request(runtime, "/%2e%2e/secret.txt")[0] == 404
        post_status, post_headers, _ = _request(runtime, "/api/status", method="POST")
        assert post_status == 405
        assert post_headers["Allow"] == "GET, HEAD"


def test_runtime_degrades_cleanly_before_first_publication(tmp_path: Path) -> None:
    with DashboardHTTPRuntime(tmp_path, port=0, renderer=_renderer) as runtime:
        status = _json_request(runtime, "/api/status")
        assert status["runtime_status"] == "DEGRADED"
        assert status["product_status"] == "BLOCKED"
        assert status["product_status_reasons"] == ["NO_ACCEPTED_V3_SNAPSHOT"]
        assert status["trading_authorized"] is False
        assert status["latest_session"] is None
        assert status["update"]["status"] == "UNKNOWN"
        assert _request(runtime, "/")[0] == 503
        assert _request(runtime, "/api/snapshot")[0] == 503
        assert _json_request(runtime, "/healthz")["ok"] is True


def test_conditional_model_fallback_marks_product_degraded_without_trade_authority(
    tmp_path: Path,
) -> None:
    session = "2026-08-18"
    payload = _publish(tmp_path, session)
    payload["probability_judgment"]["acute_front_stress_5d"] = {
        "event_status": "ELIGIBLE",
        "model_status": "BASE_RATE_ONLY",
        "probability_kind": "HISTORICAL_REFERENCE",
    }
    snapshot_path = tmp_path / "outputs" / "daily" / f"{session}.json"
    write_json(payload, snapshot_path)
    write_json(
        with_snapshot_publication_binding(
            {"session_date": session, "passed": True}, snapshot_path
        ),
        tmp_path / "artifacts" / "acceptance" / f"real_acceptance_{session}.json",
    )

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=_renderer) as runtime:
        status = _json_request(runtime, "/api/status")

    assert status["product_status"] == "DEGRADED"
    assert status["product_status_reasons"] == [
        "CONDITIONAL_MODEL_FALLBACK:acute_front_stress_5d"
    ]
    assert status["trading_authorized"] is False


def test_head_returns_headers_without_body(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-18")
    with DashboardHTTPRuntime(tmp_path, port=0, renderer=_renderer) as runtime:
        status, headers, body = _request(runtime, "/api/status", method="HEAD")
    assert status == 200
    assert int(headers["Content-Length"]) > 0
    assert body == b""


@pytest.mark.parametrize(
    ("document", "expected_suffix"),
    [
        ("<html><body>x</body></html>", "</body></html>"),
        ("<html>x</html>", "</html>"),
    ],
)
def test_polling_injection_is_idempotent(
    document: str,
    expected_suffix: str,
) -> None:
    injected = inject_runtime_polling(document, "2026-08-18", interval_ms=1_000)
    twice = inject_runtime_polling(injected, "2026-08-18", interval_ms=1_000)
    assert injected == twice
    assert injected.count('id="matvix-runtime-poll"') == 1
    assert injected.endswith(expected_suffix) or expected_suffix == "</html>"


def test_existing_dashboard_poller_receives_same_session_revision_token() -> None:
    document = '<html><body data-session-date="2026-08-18"><script id="matvix-runtime-poll"></script></body></html>'
    revision = "2026-08-18:sha256:replacement:123"

    injected = inject_runtime_polling(document, "2026-08-18", revision=revision)
    twice = inject_runtime_polling(injected, "2026-08-18", revision=revision)

    assert injected == twice
    assert injected.count('id="matvix-runtime-poll"') == 1
    assert f'data-dashboard-revision="{revision}"' in injected


def test_runtime_validates_port_and_poll_interval(tmp_path: Path) -> None:
    factories: list[Callable[[], DashboardHTTPRuntime]] = [
        lambda: DashboardHTTPRuntime(tmp_path, port=-1),
        lambda: DashboardHTTPRuntime(tmp_path, port=65_536),
        lambda: DashboardHTTPRuntime(tmp_path, poll_interval_seconds=0),
    ]
    for factory in factories:
        with pytest.raises(ValueError):
            factory()


def test_second_dashboard_instance_cannot_replace_running_instance(tmp_path: Path) -> None:
    _publish(tmp_path, "2026-08-18")

    with DashboardHTTPRuntime(tmp_path, port=0, renderer=_renderer) as primary:
        second = DashboardHTTPRuntime(
            tmp_path,
            host=primary.address[0],
            port=primary.address[1],
            renderer=_renderer,
        )
        with pytest.raises(OSError) as error:
            second.start()

        assert error.value.errno == errno.EADDRINUSE
        assert second.is_running is False
        assert _json_request(primary, "/api/status")["runtime_status"] == "RUNNING"

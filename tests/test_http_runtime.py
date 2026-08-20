from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from matvix.http_runtime import (
    DashboardHTTPRuntime,
    find_latest_accepted_snapshot,
    inject_runtime_polling,
)
from matvix.storage import write_json


def _publish(
    project: Path,
    session: str,
    *,
    passed: bool = True,
    data_status: str = "OK",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_date": session,
        "decision_as_of": f"{session}T09:20:00-04:00",
        "data_status": data_status,
        "market_story": {"headline": f"session {session}"},
    }
    write_json(payload, project / "outputs" / "daily" / f"{session}.json")
    write_json(
        {"session_date": session, "passed": passed},
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
        assert "fetch('/api/status'" in document

        status = _json_request(runtime, "/api/status")
        assert status["runtime_status"] == "RUNNING"
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
        assert status["latest_session"] is None
        assert status["update"]["status"] == "UNKNOWN"
        assert _request(runtime, "/")[0] == 503
        assert _request(runtime, "/api/snapshot")[0] == 503
        assert _json_request(runtime, "/healthz")["ok"] is True


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


def test_runtime_validates_port_and_poll_interval(tmp_path: Path) -> None:
    factories: list[Callable[[], DashboardHTTPRuntime]] = [
        lambda: DashboardHTTPRuntime(tmp_path, port=-1),
        lambda: DashboardHTTPRuntime(tmp_path, port=65_536),
        lambda: DashboardHTTPRuntime(tmp_path, poll_interval_seconds=0),
    ]
    for factory in factories:
        with pytest.raises(ValueError):
            factory()

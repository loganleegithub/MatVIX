from __future__ import annotations

import json
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pandas as pd

from matvix.dashboard import render_dashboard
from matvix.pipeline import ProjectPaths
from matvix.storage import read_json, read_parquet

DashboardRenderer = Callable[
    [dict[str, Any], pd.DataFrame | None, pd.DataFrame | None], str
]


@dataclass(frozen=True)
class RuntimePaths:
    """Filesystem contract shared by the HTTP service and the daily updater."""

    root: Path

    @property
    def daily(self) -> Path:
        return self.root / "outputs" / "daily"

    @property
    def acceptance(self) -> Path:
        return self.root / "artifacts" / "acceptance"

    @property
    def update_status(self) -> Path:
        return self.root / "outputs" / "runtime" / "update_status.json"


@dataclass(frozen=True)
class AcceptedSnapshot:
    session_date: str
    snapshot_path: Path
    acceptance_path: Path
    payload: dict[str, Any]
    published_at: str
    snapshot_mtime_ns: int
    acceptance_mtime_ns: int

    @property
    def dashboard_revision(self) -> str:
        return (
            f"{self.session_date}:{self.snapshot_mtime_ns}:{self.acceptance_mtime_ns}"
        )


def _iso_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()


def _safe_session(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    normalized = parsed.isoformat()
    return normalized if normalized == value else None


def _stable_json(path: Path) -> tuple[dict[str, Any], int, int] | None:
    """Read one atomically replaced JSON artifact without caching across a race."""

    for _ in range(2):
        try:
            before = path.stat()
            payload = read_json(path)
            after = path.stat()
        except (OSError, ValueError):
            return None
        before_token = (before.st_ino, before.st_mtime_ns, before.st_size)
        after_token = (after.st_ino, after.st_mtime_ns, after.st_size)
        if before_token == after_token:
            return payload, after.st_mtime_ns, after.st_size
    return None


def find_latest_accepted_snapshot(project_dir: str | Path) -> AcceptedSnapshot | None:
    """Resolve the newest snapshot that has passed the real-data acceptance gate.

    Daily JSON files are build artifacts, not publications by themselves.  The
    HTTP layer therefore publishes only the intersection of a passing acceptance
    receipt and a matching ``data_status=OK`` daily snapshot.
    """

    paths = RuntimePaths(Path(project_dir).resolve())
    if not paths.acceptance.is_dir():
        return None
    candidates: list[tuple[date, Path, str, int]] = []
    for acceptance_path in paths.acceptance.glob("real_acceptance_*.json"):
        loaded_receipt = _stable_json(acceptance_path)
        if loaded_receipt is None:
            continue
        receipt, acceptance_mtime_ns, _ = loaded_receipt
        session = _safe_session(receipt.get("session_date"))
        if receipt.get("passed") is not True or session is None:
            continue
        candidates.append(
            (date.fromisoformat(session), acceptance_path, session, acceptance_mtime_ns)
        )

    for _, acceptance_path, session, acceptance_mtime_ns in sorted(
        candidates, key=lambda candidate: candidate[0], reverse=True
    ):
        snapshot_path = paths.daily / f"{session}.json"
        loaded_snapshot = _stable_json(snapshot_path)
        if loaded_snapshot is None:
            continue
        payload, snapshot_mtime_ns, _ = loaded_snapshot
        if payload.get("session_date") != session or payload.get("data_status") != "OK":
            continue
        # A receipt from an earlier same-session build cannot authorize a newly
        # replaced snapshot.  The daily publisher writes the receipt last.
        if acceptance_mtime_ns < snapshot_mtime_ns:
            continue
        published_at = datetime.fromtimestamp(
            acceptance_mtime_ns / 1_000_000_000, tz=UTC
        ).isoformat()
        return AcceptedSnapshot(
            session_date=session,
            snapshot_path=snapshot_path,
            acceptance_path=acceptance_path,
            payload=payload,
            published_at=published_at,
            snapshot_mtime_ns=snapshot_mtime_ns,
            acceptance_mtime_ns=acceptance_mtime_ns,
        )
    return None


def _runtime_polling_script(session: str, interval_ms: int, revision: str | None) -> str:
    encoded_session = json.dumps(session, ensure_ascii=False)
    encoded_revision = json.dumps(revision, ensure_ascii=False)
    return f"""<script id="matvix-runtime-poll">
(() => {{
  const initialSession = {encoded_session};
  const initialRevision = {encoded_revision};
  let reloading = false;
  async function checkForUpdate() {{
    if (reloading) return;
    try {{
      const response = await fetch('/api/status', {{cache: 'no-store'}});
      if (!response.ok) return;
      const status = await response.json();
      const nextSession = status.latest_snapshot_session || status.latest_session;
      const revisionChanged = status.dashboard_revision &&
        initialRevision && status.dashboard_revision !== initialRevision;
      if ((nextSession && nextSession !== initialSession) || revisionChanged) {{
        reloading = true;
        window.location.reload();
      }}
    }} catch (_error) {{
      // A transient local-service interruption is retried on the next poll.
    }}
  }}
  window.setInterval(checkForUpdate, {interval_ms});
  document.addEventListener('visibilitychange', () => {{
    if (document.visibilityState === 'visible') checkForUpdate();
  }});
}})();
</script>"""


def inject_runtime_polling(
    document: str,
    session: str,
    interval_ms: int = 60_000,
    revision: str | None = None,
) -> str:
    """Attach one small refresh hook to a standalone dashboard document."""

    marker = 'id="matvix-runtime-poll"'
    if marker in document:
        return document
    script = _runtime_polling_script(session, interval_ms, revision)
    closing_body = document.lower().rfind("</body>")
    if closing_body < 0:
        return document + script
    return document[:closing_body] + script + document[closing_body:]


class DashboardDocumentStore:
    """Resolve the current accepted publication and cache only its rendered HTML."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        renderer: DashboardRenderer = render_dashboard,
        poll_interval_ms: int = 60_000,
    ) -> None:
        if poll_interval_ms < 1:
            raise ValueError("poll_interval_ms must be positive")
        self.paths = RuntimePaths(Path(project_dir).resolve())
        self._renderer = renderer
        self._poll_interval_ms = poll_interval_ms
        self._cache_lock = threading.Lock()
        self._cached_token: tuple[str, int, int] | None = None
        self._cached_document: bytes | None = None

    def latest(self) -> AcceptedSnapshot | None:
        return find_latest_accepted_snapshot(self.paths.root)

    def document(self) -> tuple[AcceptedSnapshot, bytes] | None:
        latest = self.latest()
        if latest is None:
            return None
        token = (
            latest.session_date,
            latest.snapshot_mtime_ns,
            latest.acceptance_mtime_ns,
        )
        with self._cache_lock:
            if self._cached_token == token and self._cached_document is not None:
                return latest, self._cached_document
            history, oof = self._history_inputs()
            document = self._renderer(latest.payload, history, oof)
            document = inject_runtime_polling(
                document,
                latest.session_date,
                interval_ms=self._poll_interval_ms,
                revision=latest.dashboard_revision,
            )
            encoded = document.encode("utf-8")
            self._cached_token = token
            self._cached_document = encoded
            return latest, encoded

    def _history_inputs(self) -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
        project_paths = ProjectPaths(self.paths.root)
        history = read_parquet(project_paths.states) if project_paths.states.exists() else None
        oof = read_parquet(project_paths.oof) if project_paths.oof.exists() else None
        return history, oof


def _read_update_status(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {"status": "UNKNOWN", "reason": "UPDATE_STATUS_NOT_YET_PUBLISHED"}, None
    try:
        payload = read_json(path)
    except (OSError, ValueError):
        return {"status": "INVALID", "reason": "UPDATE_STATUS_UNREADABLE"}, _iso_mtime(path)
    return payload, _iso_mtime(path)


class DashboardHTTPRuntime:
    """Local, read-only MatVIX publication server with a testable lifecycle."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        host: str = "127.0.0.1",
        port: int = 8788,
        renderer: DashboardRenderer = render_dashboard,
        poll_interval_seconds: float = 60.0,
        log_requests: bool = False,
    ) -> None:
        if not 0 <= port <= 65_535:
            raise ValueError("port must be between 0 and 65535")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be positive")
        self.host = host
        self.port = port
        self.log_requests = log_requests
        self.paths = RuntimePaths(Path(project_dir).resolve())
        self.documents = DashboardDocumentStore(
            self.paths.root,
            renderer=renderer,
            poll_interval_ms=max(1, round(poll_interval_seconds * 1_000)),
        )
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._started_at: datetime | None = None
        self._started_monotonic: float | None = None

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return self._server is not None and (thread is None or thread.is_alive())

    @property
    def address(self) -> tuple[str, int]:
        server = self._server
        if server is None:
            raise RuntimeError("Dashboard HTTP runtime has not started")
        host, port = server.server_address[:2]
        return str(host), int(port)

    @property
    def url(self) -> str:
        host, port = self.address
        display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
        return f"http://{display_host}:{port}/"

    def start(self) -> DashboardHTTPRuntime:
        """Start the service on a background thread."""

        with self._lifecycle_lock:
            if self._server is not None:
                raise RuntimeError("Dashboard HTTP runtime is already started")
            server = self._new_server()
            self._server = server
            self._mark_started()
            thread = threading.Thread(
                target=server.serve_forever,
                name="matvix-dashboard-http",
                daemon=True,
            )
            self._thread = thread
            thread.start()
        return self

    def serve_forever(self) -> None:
        """Run the service synchronously until interrupted or stopped."""

        with self._lifecycle_lock:
            if self._server is not None:
                raise RuntimeError("Dashboard HTTP runtime is already started")
            server = self._new_server()
            self._server = server
            self._mark_started()
        try:
            server.serve_forever()
        finally:
            server.server_close()
            with self._lifecycle_lock:
                self._server = None
                self._thread = None

    def stop(self) -> None:
        with self._lifecycle_lock:
            server = self._server
            thread = self._thread
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._lifecycle_lock:
            self._server = None
            self._thread = None

    def __enter__(self) -> DashboardHTTPRuntime:
        return self.start()

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def status_payload(self) -> dict[str, Any]:
        checked_at = datetime.now(UTC).isoformat()
        latest = self.documents.latest()
        update, update_file_mtime = _read_update_status(self.paths.update_status)
        started_at = self._started_at.isoformat() if self._started_at is not None else None
        uptime = (
            max(0.0, time.monotonic() - self._started_monotonic)
            if self._started_monotonic is not None
            else 0.0
        )
        latest_session = latest.session_date if latest is not None else None
        published_at = latest.published_at if latest is not None else None
        dashboard_revision = latest.dashboard_revision if latest is not None else None
        update_time = update.get("updated_at") or update_file_mtime or published_at
        sources = update.get("sources", update.get("data_sources", {}))
        return {
            "runtime_status": "RUNNING" if latest is not None else "DEGRADED",
            "checked_at": checked_at,
            "started_at": started_at,
            "uptime_seconds": round(uptime, 3),
            "latest_session": latest_session,
            "latest_snapshot_session": latest_session,
            "last_good_session": latest_session,
            "dashboard_revision": dashboard_revision,
            "publication_date": latest_session,
            "published_at": published_at,
            "last_update_at": update_time,
            "data_status": latest.payload.get("data_status") if latest is not None else None,
            "decision_as_of": latest.payload.get("decision_as_of") if latest is not None else None,
            "data_sources": sources,
            "update": update,
        }

    def _mark_started(self) -> None:
        self._started_at = datetime.now(UTC)
        self._started_monotonic = time.monotonic()

    def _new_server(self) -> ThreadingHTTPServer:
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
                runtime._handle(self, include_body=True)

            def do_HEAD(self) -> None:  # noqa: N802 - stdlib handler API
                runtime._handle(self, include_body=False)

            def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
                runtime._write_response(
                    self,
                    405,
                    b'{"error":"METHOD_NOT_ALLOWED"}\n',
                    "application/json; charset=utf-8",
                    include_body=True,
                    extra_headers={"Allow": "GET, HEAD"},
                )

            def log_message(self, format: str, *args: Any) -> None:
                if runtime.log_requests:
                    super().log_message(format, *args)

        server = ThreadingHTTPServer((self.host, self.port), Handler)
        server.daemon_threads = True
        return server

    def _handle(self, handler: BaseHTTPRequestHandler, *, include_body: bool) -> None:
        path = urlsplit(handler.path).path
        if path in {"/", "/index.html"}:
            rendered = self.documents.document()
            if rendered is None:
                body = (
                    "<!doctype html><html lang=\"zh-CN\"><meta charset=\"utf-8\">"
                    "<title>MatVIX 尚无正式发布</title><body><h1>尚无通过验收的正式快照</h1>"
                    "<p>HTTP 服务正在运行，等待每日更新链发布首个 last-good session。</p>"
                    "</body></html>"
                ).encode()
                self._write_response(
                    handler,
                    503,
                    body,
                    "text/html; charset=utf-8",
                    include_body=include_body,
                )
                return
            _, body = rendered
            self._write_response(
                handler,
                200,
                body,
                "text/html; charset=utf-8",
                include_body=include_body,
            )
            return
        if path == "/api/status":
            self._write_json(handler, 200, self.status_payload(), include_body=include_body)
            return
        if path == "/api/snapshot":
            latest = self.documents.latest()
            if latest is None:
                self._write_json(
                    handler,
                    503,
                    {"error": "NO_ACCEPTED_SNAPSHOT"},
                    include_body=include_body,
                )
                return
            self._write_json(handler, 200, latest.payload, include_body=include_body)
            return
        if path == "/healthz":
            status = self.status_payload()
            self._write_json(
                handler,
                200,
                {
                    "ok": True,
                    "runtime_status": status["runtime_status"],
                    "latest_session": status["latest_session"],
                    "checked_at": status["checked_at"],
                },
                include_body=include_body,
            )
            return
        if path == "/favicon.ico":
            self._write_response(
                handler,
                204,
                b"",
                "image/x-icon",
                include_body=include_body,
            )
            return
        self._write_json(
            handler,
            404,
            {"error": "NOT_FOUND"},
            include_body=include_body,
        )

    def _write_json(
        self,
        handler: BaseHTTPRequestHandler,
        status: int,
        payload: dict[str, Any],
        *,
        include_body: bool,
    ) -> None:
        body = (
            json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
        self._write_response(
            handler,
            status,
            body,
            "application/json; charset=utf-8",
            include_body=include_body,
        )

    @staticmethod
    def _write_response(
        handler: BaseHTTPRequestHandler,
        status: int,
        body: bytes,
        content_type: str,
        *,
        include_body: bool,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        handler.send_response(status)
        handler.send_header("Content-Type", content_type)
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.send_header("Referrer-Policy", "same-origin")
        for name, value in (extra_headers or {}).items():
            handler.send_header(name, value)
        handler.end_headers()
        if include_body:
            handler.wfile.write(body)


def serve_dashboard_runtime(
    project_dir: str | Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8788,
    open_browser: bool = False,
) -> None:
    """Blocking CLI integration point for the local Dashboard service."""

    runtime = DashboardHTTPRuntime(project_dir, host=host, port=port)
    with runtime._lifecycle_lock:
        server = runtime._new_server()
        runtime._server = server
        runtime._mark_started()
    print(f"MatVIX Dashboard: {runtime.url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(runtime.url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        with runtime._lifecycle_lock:
            runtime._server = None


__all__ = [
    "AcceptedSnapshot",
    "DashboardDocumentStore",
    "DashboardHTTPRuntime",
    "RuntimePaths",
    "find_latest_accepted_snapshot",
    "inject_runtime_polling",
    "serve_dashboard_runtime",
]

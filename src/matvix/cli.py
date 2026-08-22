from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from matvix.acceptance import (
    build_real_acceptance_report,
    build_v2_station_acceptance,
    failed_gate_names,
    write_real_acceptance_report,
    write_v2_station_acceptance,
)
from matvix.calendar import decision_as_of
from matvix.config import project_root
from matvix.config_contract import validate_frozen_config
from matvix.daily_update import (
    DailyUpdateResult,
    DailyUpdateStatus,
    ProjectPublicationBusyError,
    frame_content_digest,
    project_publication_lock,
    read_update_status,
    refresh_official_sources,
    run_daily_update,
    with_snapshot_publication_binding,
)
from matvix.dashboard import build_dashboard_file
from matvix.data.cboe import SUPPORTED_SYMBOLS, download_cboe_core, import_cboe_history
from matvix.data.cfe import download_monthly_history, import_cfe_directory
from matvix.data.point_in_time import merge_revision_history
from matvix.data.spx import import_spx_close
from matvix.economic_probe import run_frozen_economic_probe
from matvix.http_runtime import serve_dashboard_runtime
from matvix.pipeline import (
    ProjectPaths,
    build_snapshot_payload,
    build_state_history,
    load_persisted_inputs,
    load_persisted_states,
    persist_history,
    persist_snapshot,
    resolve_persisted_probability_artifacts,
)
from matvix.probability.walk_forward import runtime_contract_status
from matvix.scheduler import (
    LaunchdPlistSpec,
    recommended_launch_agent_path,
    run_bounded_polling,
    write_launchd_plist,
)
from matvix.storage import read_json, read_parquet, write_parquet
from matvix.v2_audit import run_v2_business_audit
from matvix.v3_audit import run_v3_business_audit

app = typer.Typer(
    name="matvix",
    help="MatVIX v2: PIT VIX market narrative and calibrated transition probabilities.",
    no_args_is_help=True,
)

ProjectDir = Annotated[
    Path,
    typer.Option("--project-dir", help="Project root containing data/, outputs/, configs/."),
]
DEFAULT_PROJECT_DIR = project_root()


def _paths(project_dir: Path) -> ProjectPaths:
    return ProjectPaths(project_dir.resolve())


def _current_time() -> datetime:
    return datetime.now(UTC)


@app.command("doctor")
def doctor(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Check locked runtime versions and local artifact availability."""
    import importlib.metadata

    required = {
        "numpy": "2.3.5",
        "pandas": "2.2.3",
        "scipy": "1.17.0",
        "scikit-learn": "1.7.2",
        "pyarrow": "25.0.0",
        "jsonschema": "4.26.0",
        "typer": "0.26.3",
        "exchange-calendars": "4.13.1",
        "plotly": "6.5.2",
    }
    rows = []
    for package, expected in required.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = "MISSING"
        rows.append((package, expected, actual, "PASS" if actual == expected else "FAIL"))
    for package, expected, actual, status in rows:
        typer.echo(f"{status:4} {package:22} expected={expected:10} actual={actual}")
    typer.echo(json.dumps(runtime_contract_status(), ensure_ascii=False))
    paths = _paths(project_dir)
    for name, path in {
        "observations": paths.observations,
        "vx_contracts": paths.vx_contracts,
        "states": paths.states,
    }.items():
        typer.echo(f"{'FOUND' if path.exists() else 'MISSING':7} {name}: {path}")
    if any(status == "FAIL" for *_, status in rows):
        raise typer.Exit(code=2)


@app.command("audit-v2")
def audit_v2(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Run the frozen V1, weather-only Phase-A business audit."""
    outputs = run_v2_business_audit(project_dir)
    typer.echo(f"Wrote {outputs['daily']}")
    typer.echo(f"Wrote {outputs['summary']}")


@app.command("audit-v3")
def audit_v3(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Run the frozen V2, weather-only V3 Stage-A business audit."""

    outputs = run_v3_business_audit(project_dir)
    typer.echo(f"Wrote {outputs['daily']}")
    typer.echo(f"Wrote {outputs['summary']}")


@app.command("accept-v2-station")
def accept_v2_station(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Run the weather-only Phase-D acceptance and write its three evidence artifacts."""

    paths = _paths(project_dir)
    observations, vx_contracts = load_persisted_inputs(paths)
    features = read_parquet(paths.features)
    states = load_persisted_states(paths)
    targets, oof, _, _ = resolve_persisted_probability_artifacts(
        paths, states, formal_runtime_required=True
    )
    complete = states.loc[states["data_status"].eq("OK")]
    if complete.empty:
        raise typer.BadParameter("No data_status=OK state is available for station acceptance")
    selected = pd.Timestamp(complete["session_date"].max()).normalize()
    snapshot, _, _, _ = build_snapshot_payload(
        states,
        observations,
        vx_contracts,
        session_date=selected,
        formal_runtime_required=True,
        target_ledger=targets,
        oof_ledger=oof,
    )
    real_acceptance = build_real_acceptance_report(
        observations=observations,
        vx_contracts=vx_contracts,
        states=states,
        targets=targets,
        oof=oof,
        snapshot=snapshot,
    )
    phase_a_dir = paths.root / "outputs" / "v2_audit"
    daily, summary = build_v2_station_acceptance(
        observations=observations,
        vx_contracts=vx_contracts,
        features=features,
        states=states,
        targets=targets,
        oof=oof,
        real_acceptance=real_acceptance,
        phase_a_daily=read_parquet(phase_a_dir / "business_audit_daily.parquet"),
        phase_a_summary=read_json(phase_a_dir / "business_audit_summary.json"),
    )
    outputs = write_v2_station_acceptance(daily, summary, paths.root)
    for name, result in summary["dimensions"].items():
        typer.echo(f"{name}: {result['status']}")
    typer.echo(f"ECONOMIC_PROBE_ENTRY: {summary['economic_probe_entry']['status']}")
    for path in outputs.values():
        typer.echo(f"Wrote {path}")


@app.command("run-v2-economic-probe")
def run_v2_economic_probe(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Run the one frozen SVXY/SGOV/VXZ probe after the Phase-D entry gate."""

    root = project_dir.resolve()
    station_path = root / "outputs" / "v2_station_acceptance" / "summary.json"
    station = read_json(station_path)
    if station.get("economic_probe_entry", {}).get("status") != "PASS":
        raise typer.BadParameter(
            "Economic probe is blocked until the four key station dimensions pass"
        )
    outputs, report = run_frozen_economic_probe(
        project_root=root,
        v1_states=read_parquet(root / "outputs" / "v2_baseline" / "v1_states.parquet"),
        v2_states=read_parquet(root / "data" / "processed" / "states.parquet"),
        station_summary=station,
    )
    for probe, result in report["classifications"].items():
        typer.echo(f"{probe}: {result}")
    typer.echo(f"COMPREHENSIVE_VERDICT: {report['comprehensive_verdict']}")
    for path in outputs.values():
        typer.echo(f"Wrote {path}")


@app.command("download-data")
def download_data(
    output_dir: Annotated[Path, typer.Option(help="Raw vendor download directory.")] = Path(
        "data/raw/vendor"
    ),
    start_year: Annotated[int, typer.Option(help="First VX contract expiry year.")] = 2013,
    end_year: Annotated[int, typer.Option(help="Last VX contract expiry year.")] = date.today().year
    + 1,
    skip_vx: Annotated[bool, typer.Option(help="Download only Cboe index histories.")] = False,
) -> None:
    """Download public Cboe index histories and standard monthly CFE VX files."""
    cboe_dir = output_dir / "cboe"
    cfe_dir = output_dir / "cfe_vx"
    paths = download_cboe_core(cboe_dir)
    typer.echo(f"Downloaded {len(paths)} Cboe files to {cboe_dir}")
    if not skip_vx:
        vx_paths = download_monthly_history(start_year, end_year, cfe_dir)
        typer.echo(f"Downloaded {len(vx_paths)} standard monthly VX files to {cfe_dir}")


@app.command("import-data")
def import_data(
    cboe_dir: Annotated[Path, typer.Option(help="Directory containing SYMBOL_History.csv files.")],
    cfe_dir: Annotated[Path, typer.Option(help="Directory containing VX_YYYY-MM-DD.csv files.")],
    spx_csv: Annotated[Path, typer.Option(help="Authorized SPX DATE,CLOSE CSV.")],
    spx_source: Annotated[
        str,
        typer.Option(help="SPX source attribution (CBOE, FRED, or licensed provider name)."),
    ] = "CBOE",
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Normalize official/local-authorized files into PIT raw Parquet tables."""
    observations: list[pd.DataFrame] = []
    missing: list[str] = []
    for symbol in SUPPORTED_SYMBOLS:
        path = cboe_dir / f"{symbol}_History.csv"
        if path.exists():
            observations.append(import_cboe_history(path, symbol))
        else:
            missing.append(str(path))
    if spx_csv.exists():
        observations.append(
            import_spx_close(
                spx_csv,
                source=spx_source,
                source_symbol="SP500" if spx_source.upper() == "FRED" else "SPX",
            )
        )
    else:
        missing.append(str(spx_csv))
    if not observations:
        raise typer.BadParameter("No Cboe/SPX observations were imported")
    observation_table = pd.concat(observations, ignore_index=True)
    vx_contracts = import_cfe_directory(cfe_dir)
    paths = _paths(project_dir)
    observations_changed = True
    if paths.observations.exists():
        existing_observations = read_parquet(paths.observations)
        observation_table = merge_revision_history(
            existing_observations,
            observation_table,
            entity_columns=["series_id"],
        )
        observations_changed = len(observation_table) > len(existing_observations)
    vx_changed = True
    if paths.vx_contracts.exists():
        existing_vx = read_parquet(paths.vx_contracts)
        vx_contracts = merge_revision_history(
            existing_vx,
            vx_contracts,
            entity_columns=["contract_id"],
        )
        vx_changed = len(vx_contracts) > len(existing_vx)
    if observations_changed:
        write_parquet(observation_table, paths.observations)
    if vx_changed:
        write_parquet(vx_contracts, paths.vx_contracts)
    typer.echo(
        f"Imported observations={len(observation_table):,} "
        f"({'updated' if observations_changed else 'unchanged'}); "
        f"VX rows={len(vx_contracts):,} ({'updated' if vx_changed else 'unchanged'})"
    )
    if missing:
        typer.echo("Missing inputs (formal Cboe Core will remain incomplete):")
        for missing_path in missing:
            typer.echo(f"  - {missing_path}")


@app.command("build-history")
def build_history(
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
    reference_sessions: Annotated[int, typer.Option(help="Prior-session percentile window.")] = 756,
    minimum_valid: Annotated[int, typer.Option(help="Minimum valid prior observations.")] = 504,
) -> None:
    """Build feature and state histories from normalized raw tables."""
    paths = _paths(project_dir)
    observations, vx_contracts = load_persisted_inputs(paths)
    features, states = build_state_history(
        observations,
        vx_contracts,
        reference_sessions=reference_sessions,
        minimum_valid=minimum_valid,
    )
    persist_history(paths, observations, vx_contracts, features, states)
    counts = states["data_status"].value_counts(dropna=False).to_dict()
    typer.echo(f"Built features={len(features):,}; states={len(states):,}; status={counts}")


@app.command("build-snapshot")
def build_snapshot(
    session_date: Annotated[
        str, typer.Option("--date", help="US options session date YYYY-MM-DD.")
    ],
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
    allow_nonformal_runtime: Annotated[
        bool,
        typer.Option(
            help="Research only: permit non-1.7.2 sklearn for calibrated probability attempts."
        ),
    ] = False,
) -> None:
    """Build, validate and persist one daily MatVIX JSON snapshot."""
    paths = _paths(project_dir)
    observations, vx_contracts = load_persisted_inputs(paths)
    states = load_persisted_states(paths)
    targets, oof, contract, cache_action = resolve_persisted_probability_artifacts(
        paths,
        states,
        formal_runtime_required=not allow_nonformal_runtime,
        persist=not allow_nonformal_runtime,
    )
    payload, metadata, _, _ = build_snapshot_payload(
        states,
        observations,
        vx_contracts,
        session_date=session_date,
        formal_runtime_required=not allow_nonformal_runtime,
        target_ledger=targets,
        oof_ledger=oof,
    )
    metadata["artifact_cache"] = {
        "action": cache_action,
        "state_history": contract["state_history"],
    }
    target = persist_snapshot(paths, payload, metadata, pd.DataFrame(), pd.DataFrame())
    typer.echo(f"Wrote {target}")
    typer.echo(f"probability_artifacts={cache_action}")
    typer.echo(
        f"phase={payload['market_story']['phase']} data_status={payload['data_status']} "
        f"outlook={payload['market_story']['answers']['outlook']}"
    )


@app.command("train-probabilities")
def train_probabilities(
    session_date: Annotated[
        str | None, typer.Option("--date", help="Prediction date; latest if omitted.")
    ] = None,
    incremental: Annotated[
        bool,
        typer.Option(
            "--incremental/--full-rebuild",
            help="Reuse/append a valid cache, or explicitly rebuild every artifact.",
        ),
    ] = True,
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Increment or explicitly rebuild target, OOF and calibration artifacts."""
    paths = _paths(project_dir)
    states = load_persisted_states(paths)
    observations, vx_contracts = load_persisted_inputs(paths)
    selected = session_date or pd.to_datetime(states["session_date"]).max().date().isoformat()
    targets, oof, contract, cache_action = resolve_persisted_probability_artifacts(
        paths,
        states,
        formal_runtime_required=True,
        force_full_rebuild=not incremental,
    )
    payload, metadata, _, _ = build_snapshot_payload(
        states,
        observations,
        vx_contracts,
        session_date=selected,
        formal_runtime_required=True,
        target_ledger=targets,
        oof_ledger=oof,
    )
    metadata["artifact_cache"] = {
        "action": cache_action,
        "state_history": contract["state_history"],
    }
    target = persist_snapshot(paths, payload, metadata, pd.DataFrame(), pd.DataFrame())
    typer.echo(f"probability_artifacts={cache_action}")
    for event, result in payload["probability_judgment"].items():
        typer.echo(
            f"{event}: event={result['event_status']} model={result['model_status']} "
            f"p={result['probability']} base={result['base_rate']}"
        )
    typer.echo(f"Wrote {target}")


@app.command("accept-real")
def accept_real(
    session_date: Annotated[
        str | None,
        typer.Option("--date", help="Latest complete session by default."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Acceptance JSON; defaults under artifacts/acceptance/."),
    ] = None,
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Run the real persisted market-state and probability acceptance gates."""
    paths = _paths(project_dir)
    if session_date is None:
        preview_states = load_persisted_states(paths)
        complete = preview_states.loc[preview_states["data_status"].eq("OK")]
        if complete.empty:
            raise typer.BadParameter("No data_status=OK state is available for acceptance")
        selected = pd.to_datetime(complete["session_date"]).max().date().isoformat()
    else:
        selected = pd.Timestamp(session_date).date().isoformat()
    current = _current_time()
    try:
        with project_publication_lock(paths.root, selected, current=current):
            _accept_real_locked(paths, selected, output, current=current)
    except ProjectPublicationBusyError:
        typer.echo("BUSY: another MatVIX publisher owns the project lock")
        raise typer.Exit(code=6) from None


def _accept_real_locked(
    paths: ProjectPaths,
    selected: str,
    output: Path | None,
    *,
    current: datetime,
) -> None:
    """Recompute, compare, content-bind and sign one snapshot under the project lock."""
    observations, vx_contracts = load_persisted_inputs(paths)
    states = load_persisted_states(paths)
    state_dates = pd.to_datetime(states["session_date"]).dt.normalize()
    if not state_dates.eq(pd.Timestamp(selected)).any():
        raise typer.BadParameter(f"No state row exists for {selected}")

    targets, oof, contract, cache_action = resolve_persisted_probability_artifacts(
        paths,
        states,
        formal_runtime_required=True,
    )
    snapshot, _, _, _ = build_snapshot_payload(
        states,
        observations,
        vx_contracts,
        session_date=selected,
        formal_runtime_required=True,
        target_ledger=targets,
        oof_ledger=oof,
    )
    report = build_real_acceptance_report(
        observations=observations,
        vx_contracts=vx_contracts,
        states=states,
        targets=targets,
        oof=oof,
        snapshot=snapshot,
    )
    report["release_contract"] = {
        **asdict(validate_frozen_config(paths.root)),
        "probability_artifact_cache": cache_action,
        "probability_artifact_state_digest": contract["state_history"]["relevant_columns_digest"],
        "dashboard_state_history_digest": frame_content_digest(states),
        "dashboard_oof_digest": frame_content_digest(oof),
    }
    formal_target = (
        paths.root / "artifacts" / "acceptance" / f"real_acceptance_{selected}.json"
    )
    target = output or formal_target
    is_formal_target = target.resolve() == formal_target.resolve()
    if is_formal_target:
        formal_at = decision_as_of(pd.Timestamp(selected))
        if current < formal_at:
            raise typer.BadParameter(
                f"Formal acceptance is gated until {formal_at.isoformat()}"
            )
        snapshot_path = paths.daily_output_dir / f"{selected}.json"
        if not snapshot_path.exists():
            raise typer.BadParameter(
                f"Formal acceptance requires an existing daily snapshot: {snapshot_path}"
            )
        persisted_snapshot = read_json(snapshot_path)
        if persisted_snapshot != snapshot:
            raise typer.BadParameter(
                "Formal acceptance recomputation does not match the persisted daily snapshot; "
                "rebuild/train the snapshot before signing it"
            )
        if report["passed"]:
            report = with_snapshot_publication_binding(report, snapshot_path)
        else:
            # A failed re-audit is evidence, not a publication.  Keep it away
            # from the canonical receipt so a transient failed run cannot
            # revoke an already accepted last-good snapshot.
            target = (
                formal_target.parent
                / "attempts"
                / f"real_acceptance_{selected}_latest_failed.json"
            )
    write_real_acceptance_report(report, target)
    for gate in report["gates"]:
        typer.echo(f"{'PASS' if gate['passed'] else 'FAIL'} {gate['name']}")
    typer.echo(f"Wrote {target}")
    if not report["passed"]:
        typer.echo("failed_gates=" + ",".join(failed_gate_names(report)))
        raise typer.Exit(code=4)


@app.command("backfill")
def backfill(
    start: Annotated[str, typer.Option(help="First output session YYYY-MM-DD.")],
    end: Annotated[str, typer.Option(help="Last output session YYYY-MM-DD.")],
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Build validated daily snapshots for a bounded historical range."""
    paths = _paths(project_dir)
    states = load_persisted_states(paths)
    observations, vx_contracts = load_persisted_inputs(paths)
    frame = states.copy()
    frame["session_date"] = pd.to_datetime(frame["session_date"]).dt.normalize()
    dates = frame.loc[
        frame["session_date"].between(pd.Timestamp(start), pd.Timestamp(end)), "session_date"
    ].tolist()
    # Resolve the history contract once, then reuse the exact same sequential
    # ledgers for every as-of snapshot in the bounded range.
    targets, oof, _, cache_action = resolve_persisted_probability_artifacts(
        paths,
        states,
        formal_runtime_required=True,
    )
    typer.echo(f"probability_artifacts={cache_action}")
    for session in dates:
        payload, metadata, _, _ = build_snapshot_payload(
            states,
            observations,
            vx_contracts,
            session_date=session,
            formal_runtime_required=True,
            target_ledger=targets,
            oof_ledger=oof,
        )
        persist_snapshot(paths, payload, metadata, pd.DataFrame(), pd.DataFrame())
        typer.echo(
            f"{session.date()}: {payload['data_status']} / {payload['market_story']['phase']}"
        )
    typer.echo(f"Backfilled {len(dates)} snapshots")


@app.command("replay")
def replay(
    session_date: Annotated[str, typer.Option("--date", help="Historical session YYYY-MM-DD.")],
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
    compare_existing: Annotated[
        bool, typer.Option(help="Require byte-equivalent canonical JSON.")
    ] = False,
) -> None:
    """Recompute an arbitrary historical date from raw tables and validate determinism."""
    paths = _paths(project_dir)
    observations, vx_contracts = load_persisted_inputs(paths)
    _, states = build_state_history(observations, vx_contracts)
    targets, oof, _, cache_action = resolve_persisted_probability_artifacts(
        paths,
        states,
        formal_runtime_required=True,
        persist=False,
    )
    payload, _, _, _ = build_snapshot_payload(
        states,
        observations,
        vx_contracts,
        session_date=session_date,
        formal_runtime_required=True,
        target_ledger=targets,
        oof_ledger=oof,
    )
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if compare_existing:
        existing = read_json(paths.daily_output_dir / f"{session_date}.json")
        expected = json.dumps(existing, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if encoded != expected:
            typer.echo("REPLAY_MISMATCH")
            raise typer.Exit(code=3)
    typer.echo("REPLAY_MATCH" if compare_existing else "REPLAY_VALID")
    typer.echo(f"probability_artifacts={cache_action}")
    typer.echo(encoded)


@app.command("export-dashboard")
def export_dashboard(
    snapshot: Annotated[Path, typer.Option(help="Daily snapshot JSON path.")],
    output: Annotated[Path, typer.Option(help="Standalone HTML output path.")] = Path(
        "outputs/dashboard.html"
    ),
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Generate a standalone, offline HTML dashboard."""
    paths = _paths(project_dir)
    history = read_parquet(paths.states) if paths.states.exists() else None
    oof = read_parquet(paths.oof) if paths.oof.exists() else None
    target = build_dashboard_file(snapshot, output, history, oof)
    typer.echo(f"Wrote {target}")


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8788,
    open_browser: Annotated[bool, typer.Option(help="Open the local browser.")] = False,
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Serve the latest accepted snapshot with status and snapshot APIs."""
    serve_dashboard_runtime(
        project_dir,
        host=host,
        port=port,
        open_browser=open_browser,
    )


@app.command("daily-update")
def daily_update(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Refresh official sources and publish the due accepted session."""

    def attempt(target: pd.Timestamp, now: datetime) -> DailyUpdateResult:
        return run_daily_update(
            project_dir,
            target,
            now=now,
            refresh=refresh_official_sources,
        )

    result = run_bounded_polling(project_dir, attempt)
    typer.echo(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    if result.status in {DailyUpdateStatus.FAILED, DailyUpdateStatus.WINDOW_EXHAUSTED}:
        raise typer.Exit(code=5)


@app.command("runtime-status")
def runtime_status(project_dir: ProjectDir = DEFAULT_PROJECT_DIR) -> None:
    """Print the persisted daily updater status without changing project state."""
    payload = read_update_status(project_dir)
    if payload is None:
        typer.echo("NO_RUNTIME_STATUS")
        raise typer.Exit(code=1)
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _launchd_specs(project_dir: Path, *, python: Path, port: int) -> tuple[LaunchdPlistSpec, ...]:
    root = project_dir.resolve()
    runtime_dir = root / "outputs" / "runtime"
    return (
        LaunchdPlistSpec(
            label="com.matvix.daily-update",
            program_arguments=(
                str(python),
                "-m",
                "matvix",
                "daily-update",
                "--project-dir",
                str(root),
            ),
            working_directory=root,
            standard_out_path=runtime_dir / "daily-update.stdout.log",
            standard_error_path=runtime_dir / "daily-update.stderr.log",
            start_interval_seconds=5 * 60,
            run_at_load=True,
            keep_alive=False,
        ),
        LaunchdPlistSpec(
            label="com.matvix.dashboard",
            program_arguments=(
                str(python),
                "-m",
                "matvix",
                "serve",
                "--project-dir",
                str(root),
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ),
            working_directory=root,
            standard_out_path=runtime_dir / "dashboard.stdout.log",
            standard_error_path=runtime_dir / "dashboard.stderr.log",
            start_interval_seconds=None,
            run_at_load=True,
            keep_alive=True,
        ),
    )


def _bootstrap_launch_agent(path: Path, label: str) -> None:
    domain = f"gui/{os.getuid()}"
    loaded = subprocess.run(
        ["launchctl", "print", f"{domain}/{label}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0
    if loaded:
        subprocess.run(
            ["launchctl", "bootout", f"{domain}/{label}"],
            check=True,
            capture_output=True,
            text=True,
        )
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["launchctl", "kickstart", f"{domain}/{label}"],
        check=True,
        capture_output=True,
        text=True,
    )


@app.command("install-services")
def install_services(
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
    port: Annotated[int, typer.Option(help="Local Dashboard HTTP port.")] = 8788,
    load: Annotated[
        bool,
        typer.Option("--load/--write-only", help="Bootstrap both LaunchAgents immediately."),
    ] = False,
) -> None:
    """Write the daily updater and Dashboard LaunchAgents; optionally load them."""
    root = project_dir.resolve()
    runtime_dir = root / "outputs" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    python = Path(sys.executable).absolute()
    for spec in _launchd_specs(root, python=python, port=port):
        destination = recommended_launch_agent_path(spec.label, home=Path.home())
        target = write_launchd_plist(spec, destination)
        typer.echo(f"Wrote {target}")
        if load:
            _bootstrap_launch_agent(target, spec.label)
            typer.echo(f"Loaded {spec.label}")


@app.command("test")
def test(
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Run the full unit, integration and no-lookahead test suite."""
    command = [sys.executable, "-m", "pytest"] + (["-v"] if verbose else [])
    completed = subprocess.run(command, cwd=project_dir, check=False)
    raise typer.Exit(code=completed.returncode)


if __name__ == "__main__":
    app()

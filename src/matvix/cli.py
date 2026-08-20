from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from matvix.acceptance import (
    build_real_acceptance_report,
    failed_gate_names,
    write_real_acceptance_report,
)
from matvix.config import project_root
from matvix.config_contract import validate_frozen_config
from matvix.dashboard import build_dashboard_file, serve_dashboard
from matvix.data.cboe import SUPPORTED_SYMBOLS, download_cboe_core, import_cboe_history
from matvix.data.cfe import download_monthly_history, import_cfe_directory
from matvix.data.point_in_time import merge_revision_history
from matvix.data.spx import import_spx_close
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
from matvix.storage import read_json, read_parquet, write_parquet

app = typer.Typer(
    name="matvix",
    help="MatVIX v1: PIT VIX market narrative and calibrated transition probabilities.",
    no_args_is_help=True,
)

ProjectDir = Annotated[
    Path,
    typer.Option("--project-dir", help="Project root containing data/, outputs/, configs/."),
]
DEFAULT_PROJECT_DIR = project_root()


def _paths(project_dir: Path) -> ProjectPaths:
    return ProjectPaths(project_dir.resolve())


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
    observations, vx_contracts = load_persisted_inputs(paths)
    states = load_persisted_states(paths)
    state_dates = pd.to_datetime(states["session_date"]).dt.normalize()
    if session_date is None:
        complete = states.loc[states["data_status"].eq("OK")]
        if complete.empty:
            raise typer.BadParameter("No data_status=OK state is available for acceptance")
        selected = pd.to_datetime(complete["session_date"]).max().date().isoformat()
    else:
        selected = pd.Timestamp(session_date).date().isoformat()
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
    }
    target = output or (
        paths.root / "artifacts" / "acceptance" / f"real_acceptance_{selected}.json"
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
    snapshot: Annotated[Path, typer.Option(help="Daily snapshot JSON path.")],
    host: Annotated[str, typer.Option(help="Bind host.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port.")] = 8765,
    open_browser: Annotated[bool, typer.Option(help="Open the local browser.")] = False,
    project_dir: ProjectDir = DEFAULT_PROJECT_DIR,
) -> None:
    """Start the local no-cloud Dashboard."""
    paths = _paths(project_dir)
    history = read_parquet(paths.states) if paths.states.exists() else None
    oof = read_parquet(paths.oof) if paths.oof.exists() else None
    serve_dashboard(
        snapshot,
        host=host,
        port=port,
        open_browser=open_browser,
        history=history,
        oof=oof,
    )


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

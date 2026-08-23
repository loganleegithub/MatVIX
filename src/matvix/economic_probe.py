from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import requests
from plotly.subplots import make_subplots

from matvix.calendar import decision_as_of
from matvix.fragility_shadow import (
    SPEC_ID,
    SPEC_SHA256,
    build_v3_adapter,
    verify_frozen_replay,
)
from matvix.storage import write_json

TICKERS = ("SVXY", "SGOV", "VXZ")
PROBES = ("short", "long", "combined")
INITIAL_NAV = 10_000.0
ONE_WAY_COST = 0.0005
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
V3_STAGE_D_SHA256 = "54b4c4dd73c4f3f380e90981015b3499bd6a67fe4328c08f44bc97e7e93eba93"
SHADOW_LEDGER_FIELDS = (
    "base_short_allowed", "shadow_score", "causal_base_rate", "shadow_score_available",
    "shadow_score_kind", "qualification_status", "formal_event_id", "formal_model_status",
    "shadow_transform", "unqualified_fragility_veto_shadow", "short_allowed_v3",
)


def adapt_weather(states: pd.DataFrame, weather_version: str) -> pd.DataFrame:
    """Project either weather version onto the exact shared adapter interface."""

    mapping = {
        "carry_answer": "carry",
        "shock_answer": "shock",
        "persistence_answer": "persistence",
    }
    required = {"session_date", "data_status", *mapping}
    missing = sorted(required - set(states.columns))
    if missing:
        raise ValueError(f"Weather interface columns missing: {missing}")
    result = states[["session_date", "data_status", *mapping]].rename(columns=mapping).copy()
    result["session_date"] = pd.to_datetime(result["session_date"]).dt.normalize()
    if result["session_date"].isna().any() or result["session_date"].duplicated().any():
        raise ValueError("Weather interface requires one valid row per session")
    result["decision_as_of"] = result["session_date"].map(decision_as_of)
    result["weather_version"] = weather_version
    result["base_short_allowed"] = (
        result["data_status"].eq("OK") & result["carry"].eq("SUPPORTIVE")
        & result["shock"].eq("CALM") & result["persistence"].eq("NORMAL")
    )
    return result.sort_values("session_date").reset_index(drop=True)


def target_asset(row: pd.Series, probe: str) -> tuple[str, str]:
    if probe not in PROBES:
        raise ValueError(f"Unknown frozen probe: {probe}")
    usable = row.get("data_status") == "OK"
    base_short_allowed = bool(row.get("base_short_allowed", False))
    is_v3 = row.get("weather_version") == "V3"
    short_allowed = bool(row.get("short_allowed_v3", False)) if is_v3 else base_short_allowed
    mid_diffusion = bool(usable and row.get("persistence") == "DIFFUSING")
    defensive = (
        "UNQUALIFIED_FRAGILITY_VETO_SHADOW"
        if is_v3 and bool(row.get("unqualified_fragility_veto_shadow", False))
        else "SHADOW_SCORE_UNAVAILABLE"
        if is_v3 and base_short_allowed and not bool(row.get("shadow_score_available", False))
        else "DEFENSIVE"
    )
    if probe == "short":
        return ("SHORT_ALLOWED", "SVXY") if short_allowed else (defensive, "SGOV")
    if probe == "long":
        return (
            ("MID_DIFFUSION_CONFIRMED", "VXZ")
            if mid_diffusion
            else ("DEFENSIVE", "SGOV")
        )
    if not usable:
        return "DEFENSIVE", "SGOV"
    if mid_diffusion:
        return "MID_DIFFUSION_CONFIRMED", "VXZ"
    if short_allowed:
        return "SHORT_ALLOWED", "SVXY"
    return defensive, "SGOV"


def parse_yahoo_chart(payload: dict[str, Any], ticker: str) -> pd.DataFrame:
    chart = payload.get("chart", {})
    if not isinstance(chart, dict) or chart.get("error") is not None:
        raise ValueError(f"Yahoo chart error for {ticker}: {chart.get('error')}")
    results = chart.get("result")
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise ValueError(f"Yahoo chart result missing for {ticker}")
    result = cast(dict[str, Any], results[0])
    timestamps = result.get("timestamp")
    indicators = result.get("indicators", {})
    quotes = indicators.get("quote") if isinstance(indicators, dict) else None
    adjusted = indicators.get("adjclose") if isinstance(indicators, dict) else None
    if not (
        isinstance(timestamps, list)
        and isinstance(quotes, list)
        and len(quotes) == 1
        and isinstance(quotes[0], dict)
        and isinstance(adjusted, list)
        and len(adjusted) == 1
        and isinstance(adjusted[0], dict)
    ):
        raise ValueError(f"Yahoo OHLC/adjusted-close payload incomplete for {ticker}")
    quote = cast(dict[str, Any], quotes[0])
    adjclose = cast(dict[str, Any], adjusted[0]).get("adjclose")
    fields = {
        "raw_open": quote.get("open"),
        "raw_high": quote.get("high"),
        "raw_low": quote.get("low"),
        "raw_close": quote.get("close"),
        "volume": quote.get("volume"),
        "adjusted_close": adjclose,
    }
    if any(not isinstance(values, list) or len(values) != len(timestamps) for values in fields.values()):
        raise ValueError(f"Yahoo field length mismatch for {ticker}")
    timezone = str(cast(dict[str, Any], result.get("meta", {})).get("exchangeTimezoneName", "UTC"))
    sessions = (
        pd.to_datetime(timestamps, unit="s", utc=True)
        .tz_convert(timezone)
        .tz_localize(None)
        .normalize()
    )
    frame = pd.DataFrame({"session_date": sessions, "ticker": ticker, **fields})
    for column in fields:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["adjustment_factor"] = frame["adjusted_close"] / frame["raw_close"]
    frame["adjusted_open"] = frame["raw_open"] * frame["adjustment_factor"]
    if frame["session_date"].duplicated().any():
        raise ValueError(f"Yahoo returned duplicate sessions for {ticker}")
    return frame.sort_values("session_date").reset_index(drop=True)


def build_probe_ledger(
    weather: pd.DataFrame,
    prices: pd.DataFrame,
    *,
    probe: str,
    initial_nav: float = INITIAL_NAV,
    one_way_cost: float = ONE_WAY_COST,
) -> pd.DataFrame:
    required_price = {"session_date", "ticker", "adjusted_open"}
    missing = sorted(required_price - set(prices.columns))
    if missing:
        raise ValueError(f"Price columns missing: {missing}")
    price_frame = prices.copy()
    price_frame["session_date"] = pd.to_datetime(price_frame["session_date"]).dt.normalize()
    if price_frame.duplicated(["session_date", "ticker"]).any():
        raise ValueError("Price ledger contains duplicate ticker/session rows")
    date_sets = {
        ticker: set(price_frame.loc[price_frame["ticker"].eq(ticker), "session_date"])
        for ticker in TICKERS
    }
    if any(not dates for dates in date_sets.values()) or len({frozenset(x) for x in date_sets.values()}) != 1:
        raise ValueError("Price sessions differ across the frozen Yahoo batch")
    common = sorted(set(weather["session_date"]) & set.intersection(*date_sets.values()))
    if len(common) < 3:
        raise ValueError("Fewer than three common weather/price sessions")
    opens = price_frame.pivot(index="session_date", columns="ticker", values="adjusted_open")
    missing_open = opens.loc[common, list(TICKERS)].isna()
    if missing_open.any().any():
        first = missing_open.stack().loc[lambda values: values].index[0]
        raise ValueError(f"Missing adjusted-open for {first[1]} on {first[0].date()}")
    weather_rows = weather.set_index("session_date")
    records: list[dict[str, Any]] = []
    nav = float(initial_nav)
    peak = nav
    previous_asset: str | None = None
    for index in range(1, len(common) - 1):
        signal_session = pd.Timestamp(common[index - 1])
        execution_session = pd.Timestamp(common[index])
        return_session = pd.Timestamp(common[index + 1])
        signal = weather_rows.loc[signal_session]
        if isinstance(signal, pd.DataFrame):
            raise ValueError(f"Duplicate weather session: {signal_session.date()}")
        probe_state, asset = target_asset(signal, probe)
        turnover = 1.0 if previous_asset is None else 0.0 if previous_asset == asset else 2.0
        nav_pre = nav
        cost = nav_pre * one_way_cost * turnover
        nav_after_cost = nav_pre - cost
        execution_price = float(opens.loc[execution_session, asset])
        return_price = float(opens.loc[return_session, asset])
        gross_return = return_price / execution_price - 1.0
        gross_pnl = nav_after_cost * gross_return
        nav = nav_after_cost + gross_pnl
        net_return = nav / nav_pre - 1.0
        pnl = nav - nav_pre
        peak = max(peak, nav)
        records.append(
            {
                "weather_version": str(signal["weather_version"]),
                "probe": probe,
                "signal_session": signal_session,
                "decision_as_of": signal["decision_as_of"],
                "execution_session": execution_session,
                "return_through_session": return_session,
                "data_status": str(signal["data_status"]),
                "carry": str(signal["carry"]),
                "shock": str(signal["shock"]),
                "persistence": str(signal["persistence"]),
                **{field: signal.get(field) for field in SHADOW_LEDGER_FIELDS},
                "probe_state": probe_state,
                "target_asset": asset,
                "adjusted_execution_price": execution_price,
                "adjusted_return_price": return_price,
                "turnover": turnover,
                "cost": cost,
                "nav_pre": nav_pre,
                "nav_after_cost": nav_after_cost,
                "gross_return": gross_return,
                "gross_pnl": gross_pnl,
                "net_return": net_return,
                "pnl": pnl,
                "nav": nav,
                "drawdown": nav / peak - 1.0,
            }
        )
        previous_asset = asset
    return pd.DataFrame(records)


def classify_probe(
    v1: dict[str, Any], v2: dict[str, Any], *, eligible: bool = True
) -> str:
    if not eligible:
        return "NOT_ELIGIBLE"
    final_higher = float(v2["final_nav"]) > float(v1["final_nav"])
    final_lower = float(v2["final_nav"]) < float(v1["final_nav"])
    drawdown_nonworse = float(v2["max_drawdown"]) >= float(v1["max_drawdown"])
    rolling_nonworse = float(v2["worst_rolling_20d"]) >= float(v1["worst_rolling_20d"])
    risk_improved = (
        float(v2["max_drawdown"]) > float(v1["max_drawdown"])
        or float(v2["worst_rolling_20d"]) > float(v1["worst_rolling_20d"])
    )
    risk_worsened = not drawdown_nonworse or not rolling_nonworse
    if final_higher and drawdown_nonworse and rolling_nonworse and risk_improved:
        return "POSITIVE"
    if final_lower and risk_worsened:
        return "NEGATIVE"
    return "MIXED"


def _atomic_bytes(data: bytes, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_text(text: str, path: Path) -> None:
    _atomic_bytes(text.encode("utf-8"), path)


def _load_price_batch(manifest_path: Path, project_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Economic price manifest must be an object: {manifest_path}")
    requests_map = manifest.get("requests", {})
    frames = []
    for ticker in TICKERS:
        entry = requests_map.get(ticker) if isinstance(requests_map, dict) else None
        if not isinstance(entry, dict):
            raise ValueError(f"Economic price manifest missing {ticker}")
        raw_path = project_root / str(entry["raw_path"])
        raw = raw_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
            raise ValueError(f"Economic raw response digest mismatch: {ticker}")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"Economic raw response must be an object: {ticker}")
        frames.append(parse_yahoo_chart(payload, ticker))
    loaded = dict(manifest)
    loaded["reused_existing_batch"] = True
    return pd.concat(frames, ignore_index=True), loaded


def fetch_yahoo_price_batch(
    project_root: str | Path,
    *,
    first_session: pd.Timestamp,
    last_session: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Fetch or deterministically reuse one same-interface, same-parameter batch."""

    root = Path(project_root).resolve()
    raw_root = root / "data" / "raw" / "economic_probe"
    period1 = int(
        (pd.Timestamp(first_session).normalize() - pd.Timedelta(days=7))
        .tz_localize("UTC")
        .timestamp()
    )
    period2 = int(
        (pd.Timestamp(last_session).normalize() + pd.Timedelta(days=7))
        .tz_localize("UTC")
        .timestamp()
    )
    parameters: dict[str, Any] = {
        "period1": period1,
        "period2": period2,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    }
    for candidate in sorted(raw_root.glob("*/manifest.json"), reverse=True):
        existing = json.loads(candidate.read_text(encoding="utf-8"))
        if (
            isinstance(existing, dict)
            and existing.get("source") == "Yahoo Finance Chart JSON API"
            and existing.get("parameters") == parameters
            and existing.get("tickers") == list(TICKERS)
        ):
            return _load_price_batch(candidate, root)

    started = datetime.now(UTC)
    batch_id = started.strftime("%Y%m%dT%H%M%S.%fZ")
    batch_dir = raw_root / batch_id
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 MatVIX-V2-Economic-Probe/1.0"
        }
    )
    request_manifest: dict[str, Any] = {}
    frames: list[pd.DataFrame] = []
    for ticker in TICKERS:
        url = YAHOO_CHART_URL.format(ticker=ticker)
        fetched_at = datetime.now(UTC)
        response = session.get(url, params=parameters, timeout=30)
        if response.status_code != 200:
            raise ValueError(f"Yahoo HTTP {response.status_code} for {ticker}; no fallback allowed")
        raw = response.content
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"Yahoo response must be an object for {ticker}")
        frame = parse_yahoo_chart(payload, ticker)
        raw_path = batch_dir / f"{ticker}.json"
        _atomic_bytes(raw, raw_path)
        request_manifest[ticker] = {
            "url": url,
            "final_url": response.url,
            "parameters": parameters,
            "fetched_at_utc": fetched_at.isoformat(),
            "status_code": response.status_code,
            "content_length": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "raw_path": str(raw_path.relative_to(root)),
            "rows": len(frame),
        }
        frames.append(frame)
    manifest = {
        "batch_id": batch_id,
        "source": "Yahoo Finance Chart JSON API",
        "interface": YAHOO_CHART_URL,
        "tickers": list(TICKERS),
        "parameters": parameters,
        "batch_started_at_utc": started.isoformat(),
        "batch_finished_at_utc": datetime.now(UTC).isoformat(),
        "requests": request_manifest,
        "reused_existing_batch": False,
    }
    write_json(manifest, batch_dir / "manifest.json")
    return pd.concat(frames, ignore_index=True), manifest


def probe_metrics(ledger: pd.DataFrame, *, initial_nav: float = INITIAL_NAV) -> dict[str, Any]:
    if ledger.empty or len(ledger) < 20:
        raise ValueError("Probe ledger has insufficient completed open-to-open sessions")
    rolling = ledger["rolling_20d_return"].dropna()
    if rolling.empty:
        raise ValueError("Probe ledger cannot form a 20-session rolling return")
    gross_final = float(initial_nav * (1.0 + ledger["gross_return"]).prod())
    return {
        "sessions": int(len(ledger)),
        "first_signal_session": ledger.iloc[0]["signal_session"].date().isoformat(),
        "first_execution_session": ledger.iloc[0]["execution_session"].date().isoformat(),
        "last_return_through_session": ledger.iloc[-1]["return_through_session"].date().isoformat(),
        "initial_nav": float(initial_nav),
        "gross_final_nav": gross_final,
        "final_nav": float(ledger.iloc[-1]["nav"]),
        "total_return": float(ledger.iloc[-1]["nav"] / initial_nav - 1.0),
        "max_drawdown": float(ledger["drawdown"].min()),
        "worst_rolling_20d": float(rolling.min()),
        "trade_count_including_initial": int(ledger["turnover"].gt(0).sum()),
        "asset_switches": int(ledger["turnover"].eq(2.0).sum()),
        "total_turnover": float(ledger["turnover"].sum()),
        "total_cost_paid": float(ledger["cost"].sum()),
        "compounded_cost_drag": float(gross_final - ledger.iloc[-1]["nav"]),
        "target_asset_sessions": {
            str(key): int(value) for key, value in ledger["target_asset"].value_counts().items()
        },
    }


def _common_sessions(weather: dict[str, pd.DataFrame], prices: pd.DataFrame) -> list[pd.Timestamp]:
    date_sets = [set(frame["session_date"]) for frame in weather.values()]
    date_sets.extend(
        set(prices.loc[prices["ticker"].eq(ticker), "session_date"]) for ticker in TICKERS
    )
    common = sorted(set.intersection(*date_sets))
    if len(common) < 22:
        raise ValueError("Insufficient common V1/V2/SVXY/SGOV/VXZ sessions")
    return [pd.Timestamp(value).normalize() for value in common]


def _diffusion_cluster_returns(
    weather: dict[str, pd.DataFrame], prices: pd.DataFrame, common: list[pd.Timestamp]
) -> list[dict[str, Any]]:
    opens = prices.pivot(index="session_date", columns="ticker", values="adjusted_open")
    common_index = {session: index for index, session in enumerate(common)}
    records: list[dict[str, Any]] = []
    for version, frame in weather.items():
        indexed = frame.set_index("session_date").loc[common]
        active = indexed["data_status"].eq("OK") & indexed["persistence"].eq("DIFFUSING")
        starts = active & ~active.shift(1, fill_value=False)
        ends = active & ~active.shift(-1, fill_value=False)
        for cluster_id, (start, end) in enumerate(zip(indexed.index[starts], indexed.index[ends], strict=True), 1):
            start_index, end_index = common_index[start], common_index[end]
            if end_index + 2 >= len(common):
                continue
            execution_start = common[start_index + 1]
            execution_end = common[end_index + 2]
            vxz_return = float(opens.loc[execution_end, "VXZ"] / opens.loc[execution_start, "VXZ"] - 1)
            sgov_return = float(
                opens.loc[execution_end, "SGOV"] / opens.loc[execution_start, "SGOV"] - 1
            )
            records.append(
                {
                    "weather_version": version,
                    "cluster_id": cluster_id,
                    "signal_start": start.date().isoformat(),
                    "signal_end": end.date().isoformat(),
                    "signal_sessions": end_index - start_index + 1,
                    "execution_start": execution_start.date().isoformat(),
                    "execution_end": execution_end.date().isoformat(),
                    "vxz_return": vxz_return,
                    "sgov_return": sgov_return,
                    "vxz_minus_sgov": vxz_return - sgov_return,
                }
            )
    return records


def _worst_svxy_exposure(
    ledger: pd.DataFrame, prices: pd.DataFrame, common: list[pd.Timestamp]
) -> list[dict[str, Any]]:
    opens = prices.loc[prices["ticker"].eq("SVXY")].set_index("session_date")["adjusted_open"]
    returns = pd.Series(
        [float(opens.loc[common[index + 1]] / opens.loc[common[index]] - 1) for index in range(1, len(common) - 1)],
        index=common[1:-1],
    )
    worst = returns.nsmallest(20)
    records: list[dict[str, Any]] = []
    for session, value in worst.items():
        row: dict[str, Any] = {
            "execution_session": session.date().isoformat(),
            "svxy_open_to_open_return": float(value),
        }
        selected = ledger.loc[ledger["execution_session"].eq(session)]
        for item in selected.itertuples(index=False):
            row[f"{item.weather_version}_{item.probe}_asset"] = item.target_asset
        records.append(row)
    return records


def _daily_attribution(
    ledger: pd.DataFrame, classifications: dict[str, str], versions: tuple[str, str]
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for probe, classification in classifications.items():
        if classification not in {"MIXED", "NEGATIVE"}:
            continue
        baseline = ledger.loc[ledger["weather_version"].eq(versions[0])
                              & ledger["probe"].eq(probe)].set_index("execution_session")
        candidate = ledger.loc[ledger["weather_version"].eq(versions[1])
                               & ledger["probe"].eq(probe)].set_index("execution_session")
        joined = baseline.add_prefix("baseline_").join(
            candidate.add_prefix("candidate_"), how="inner"
        )
        joined["nav_gap"] = joined["candidate_nav"] - joined["baseline_nav"]
        joined["nav_gap_change"] = joined["nav_gap"].diff().fillna(joined["nav_gap"])
        records, numeric = [], ("gross_return", "cost", "net_return", "nav")
        for session, row in joined.iterrows():
            records.append({
                "execution_session": pd.Timestamp(session).date().isoformat(),
                "baseline_asset": row["baseline_target_asset"],
                "candidate_asset": row["candidate_target_asset"],
                **{f"baseline_{name}": float(row[f"baseline_{name}"]) for name in numeric},
                **{f"candidate_{name}": float(row[f"candidate_{name}"]) for name in numeric},
                "nav_gap": float(row["nav_gap"]), "nav_gap_change": float(row["nav_gap_change"]),
            })
        result[probe] = records
    return result


def _v3_classifications(
    metrics: dict[str, dict[str, dict[str, Any]]],
    ledger: pd.DataFrame,
    versions: tuple[str, str],
) -> tuple[dict[str, str], dict[str, bool]]:
    baseline, candidate = (metrics[version] for version in versions)
    short_gates = {
        "final_nav_strictly_higher": candidate["short"]["final_nav"] > baseline["short"]["final_nav"],
        "total_return_strictly_higher": candidate["short"]["total_return"] > baseline["short"]["total_return"],
        "max_drawdown_strictly_better": candidate["short"]["max_drawdown"] > baseline["short"]["max_drawdown"],
        "worst_20d_strictly_better": candidate["short"]["worst_rolling_20d"] > baseline["short"]["worst_rolling_20d"],
    }
    combined_gates = {
        "combined_final_nav_nonworse": candidate["combined"]["final_nav"] >= baseline["combined"]["final_nav"],
        "combined_max_drawdown_nonworse": candidate["combined"]["max_drawdown"] >= baseline["combined"]["max_drawdown"],
        "combined_worst_20d_nonworse": candidate["combined"]["worst_rolling_20d"] >= baseline["combined"]["worst_rolling_20d"],
    }
    exact_fields = ("signal_session", "decision_as_of", "execution_session", "return_through_session",
                    "data_status", "persistence", "probe_state", "target_asset",
                    "adjusted_execution_price", "adjusted_return_price", "turnover", "cost",
                    "gross_return", "gross_pnl", "net_return", "pnl", "nav", "drawdown")
    long_rows = [ledger.loc[
        ledger["weather_version"].eq(version) & ledger["probe"].eq("long"), exact_fields
    ].reset_index(drop=True) for version in versions]
    gates = {**short_gates, "long_daily_exact": long_rows[0].equals(long_rows[1]), **combined_gates}
    return {
        "short": "POSITIVE" if all(short_gates.values()) else "MIXED",
        "long": "POSITIVE" if gates["long_daily_exact"] else "NEGATIVE",
        "combined": "POSITIVE" if all(combined_gates.values()) else "MIXED",
    }, gates


def _build_economic_comparison(
    *,
    weather: dict[str, pd.DataFrame],
    prices: pd.DataFrame,
    source_manifest: dict[str, Any],
    station_summary: dict[str, Any],
    v3_contract: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dimensions = cast(dict[str, Any], station_summary.get("dimensions", {}))
    required_dimensions = tuple(station_summary.get("dimension_order", ())) if v3_contract else (
        "DATA", "TENOR", "STATE_TIMING", "PROBABILITY_INTEGRITY"
    )
    if any(cast(dict[str, Any], dimensions.get(name, {})).get("status") != "PASS" for name in required_dimensions):
        raise ValueError("Economic probe is blocked by a non-PASS station dimension")
    versions = tuple(weather)
    if len(versions) != 2:
        raise ValueError("Economic comparison requires exactly two weather versions")
    prices = prices.copy()
    prices["session_date"] = pd.to_datetime(prices["session_date"]).dt.normalize()
    common = _common_sessions(weather, prices)
    bounded_prices = prices.loc[prices["session_date"].between(common[0], common[-1])]
    price_dates = {
        ticker: set(bounded_prices.loc[bounded_prices["ticker"].eq(ticker), "session_date"])
        for ticker in TICKERS
    }
    if len({frozenset(values) for values in price_dates.values()}) != 1:
        raise ValueError("Yahoo batch has unequal asset sessions; no silent intersection allowed")
    common_prices = prices.loc[prices["session_date"].isin(common)].copy()
    if common_prices["adjusted_open"].isna().any() or (~np.isfinite(common_prices["adjusted_open"])).any():
        raise ValueError("Missing adjusted-open in the common economic-probe range")

    ledgers = [
        build_probe_ledger(weather[version], common_prices, probe=probe)
        for version in versions
        for probe in PROBES
    ]
    ledger = pd.concat(ledgers, ignore_index=True)
    ledger["rolling_20d_return"] = ledger.groupby(["weather_version", "probe"])[
        "net_return"
    ].transform(lambda values: (1.0 + values).rolling(20).apply(np.prod, raw=True) - 1.0)
    metrics = {
        version: {
            probe: probe_metrics(
                ledger.loc[
                    ledger["weather_version"].eq(version) & ledger["probe"].eq(probe)
                ]
            )
            for probe in PROBES
        }
        for version in versions
    }
    clusters = _diffusion_cluster_returns(weather, common_prices, common)
    diffusion_counts = {
        version: sum(record["weather_version"] == version for record in clusters)
        for version in versions
    }
    eligible = {
        "short": True,
        "long": all(count > 0 for count in diffusion_counts.values()),
        "combined": True,
    }
    if v3_contract:
        classifications, frozen_gates = _v3_classifications(metrics, ledger, versions)
    else:
        classifications = {
            probe: classify_probe(
                metrics[versions[0]][probe], metrics[versions[1]][probe], eligible=eligible[probe]
            ) for probe in PROBES
        }
        frozen_gates = {}
    worst_exposure = _worst_svxy_exposure(ledger, common_prices, common)
    report = {
        "probe_version": "3.0.0" if v3_contract else "1.0.0",
        "comparison_versions": list(versions),
        "contract": {
            "initial_nav_usd": INITIAL_NAV,
            "assets": list(TICKERS),
            "one_way_cost": ONE_WAY_COST,
            "execution": "signal t EOD -> next common session open; adjusted open-to-open",
            "adapter_fields": [
                "session_date",
                "decision_as_of",
                "data_status",
                "carry",
                "shock",
                "persistence",
                *(SHADOW_LEDGER_FIELDS if v3_contract else ()),
            ],
            "parameters_tuned_after_results": False,
        },
        "price_source": source_manifest,
        "common_range": {
            "first_signal_session": common[0].date().isoformat(),
            "first_execution_session": common[1].date().isoformat(),
            "last_return_through_session": common[-1].date().isoformat(),
            "common_sessions": len(common),
        },
        "metrics": metrics,
        "eligibility": eligible,
        "classifications": classifications,
        "frozen_v3_gates": frozen_gates,
        "comprehensive_verdict": (
            "COMPREHENSIVE_POSITIVE"
            if all(value == "POSITIVE" for value in classifications.values() if value != "NOT_ELIGIBLE")
            else "NO_COMPREHENSIVE_INCREMENT"
        ),
        "worst_20_svxy_day_exposure": worst_exposure,
        "diffusing_cluster_vxz_vs_sgov": clusters,
        "diffusing_cluster_counts": diffusion_counts,
        "daily_attribution_for_nonpositive_probes": _daily_attribution(
            ledger, classifications, versions
        ),
        "evidence_boundary": {
            "fixed_probe_only": True,
            "not_strategy_optimization": True,
            "not_production_performance": True,
            "formal_station_probability_model_not_used": True,
            "unqualified_fragility_shadow_used": v3_contract,
        },
    }
    return ledger.sort_values(["weather_version", "probe", "execution_session"]).reset_index(
        drop=True
    ), report


def build_economic_probe(
    *, v1_states: pd.DataFrame, v2_states: pd.DataFrame, prices: pd.DataFrame,
    source_manifest: dict[str, Any], station_summary: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    return _build_economic_comparison(
        weather={"V1": adapt_weather(v1_states, "V1"), "V2": adapt_weather(v2_states, "V2")},
        prices=prices, source_manifest=source_manifest, station_summary=station_summary,
    )


def _economic_figures(
    ledger: pd.DataFrame, report: dict[str, Any]
) -> list[tuple[str, go.Figure]]:
    versions = tuple(cast(list[str], report["comparison_versions"]))
    colors = {
        ("V1", "short"): "#8c8c8c",
        ("V2", "short"): "#f59e0b",
        ("V1", "long"): "#64748b",
        ("V2", "long"): "#0ea5e9",
        ("V1", "combined"): "#a78bfa",
        ("V2", "combined"): "#10b981",
        ("V3", "short"): "#f97316",
        ("V3", "long"): "#38bdf8",
        ("V3", "combined"): "#22c55e",
    }
    nav, underwater, rolling = go.Figure(), go.Figure(), go.Figure()
    series_figures = {
        "nav": (nav, "USD NAV"), "drawdown": (underwater, "Drawdown"),
        "rolling_20d_return": (rolling, "Rolling 20-session return"),
    }
    for version in versions:
        for probe in PROBES:
            frame = ledger.loc[ledger["weather_version"].eq(version) & ledger["probe"].eq(probe)]
            name = f"{version} {probe}"
            for column, (figure, _) in series_figures.items():
                figure.add_trace(go.Scatter(
                    x=frame["return_through_session"], y=frame[column], name=name,
                    line={"color": colors[(version, probe)]},
                ))
    for figure, title in series_figures.values():
        figure.update_layout(yaxis_title=title, hovermode="x unified")

    worst = cast(list[dict[str, Any]], report["worst_20_svxy_day_exposure"])
    exposure_rows = [f"{version} {probe}" for version in versions for probe in PROBES]
    asset_code = {"SGOV": 0, "SVXY": 1, "VXZ": 2}
    exposure = go.Figure(
        go.Heatmap(
            x=[record["execution_session"] for record in worst],
            y=exposure_rows,
            z=[
                [
                    asset_code.get(
                        str(record.get(f"{row.split()[0]}_{row.split()[1]}_asset")), -1
                    )
                    for record in worst
                ]
                for row in exposure_rows
            ],
            zmin=0,
            zmax=2,
            colorscale=[
                [0.0, "#94a3b8"],
                [0.33, "#94a3b8"],
                [0.34, "#f59e0b"],
                [0.66, "#f59e0b"],
                [0.67, "#0ea5e9"],
                [1.0, "#0ea5e9"],
            ],
            colorbar={"tickvals": [0, 1, 2], "ticktext": ["SGOV", "SVXY", "VXZ"]},
            customdata=np.asarray(
                [[record["svxy_open_to_open_return"] for record in worst]] * len(exposure_rows)
            ),
            hovertemplate="%{y}<br>%{x}<br>asset code=%{z}<br>SVXY=%{customdata:.2%}<extra></extra>",
        )
    )

    combined = ledger.loc[ledger["probe"].eq("combined")].copy()
    timeline = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08)
    timeline_frames = {
        version: combined.loc[combined["weather_version"].eq(version)].sort_values(
            "execution_session"
        )
        for version in versions
    }
    timeline_x = [
        str(value) for value in timeline_frames[versions[0]]["execution_session"].tolist()
    ]
    for version in versions[1:]:
        candidate_x = [
            str(value) for value in timeline_frames[version]["execution_session"].tolist()
        ]
        if candidate_x != timeline_x:
            raise ValueError("Economic comparison timelines do not share execution sessions")
    timeline.add_trace(
        go.Heatmap(
            x=timeline_x,
            y=list(versions),
            z=[
                [
                    asset_code[str(value)]
                    for value in timeline_frames[version]["target_asset"]
                ]
                for version in versions
            ],
            zmin=0,
            zmax=2,
            colorscale=[
                [0.0, "#94a3b8"],
                [0.33, "#94a3b8"],
                [0.34, "#f59e0b"],
                [0.66, "#f59e0b"],
                [0.67, "#0ea5e9"],
                [1.0, "#0ea5e9"],
            ],
            colorbar={"tickvals": [0, 1, 2], "ticktext": ["SGOV", "SVXY", "VXZ"]},
            hovertemplate="%{y}<br>%{x}<br>position code=%{z}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    persistence_code = {"NORMAL": 0, "DIFFUSING": 1, "PERSISTENT": 2}
    timeline.add_trace(
        go.Heatmap(
            x=timeline_x,
            y=list(versions),
            z=[
                [
                    persistence_code.get(str(value), 3)
                    for value in timeline_frames[version]["persistence"]
                ]
                for version in versions
            ],
            zmin=0,
            zmax=3,
            colorscale=[
                [0.0, "#10b981"],
                [0.24, "#10b981"],
                [0.25, "#0ea5e9"],
                [0.49, "#0ea5e9"],
                [0.50, "#ef4444"],
                [0.74, "#ef4444"],
                [0.75, "#64748b"],
                [1.0, "#64748b"],
            ],
            colorbar={
                "tickvals": [0, 1, 2, 3],
                "ticktext": ["NORMAL", "DIFFUSING", "PERSISTENT", "OTHER"],
                "x": 1.12,
            },
            hovertemplate="%{y}<br>%{x}<br>persistence code=%{z}<extra></extra>",
        ),
        row=2,
        col=1,
    )
    timeline.update_yaxes(title_text="Combined position", row=1, col=1)
    timeline.update_yaxes(title_text="Persistence", row=2, col=1)

    metrics = cast(dict[str, dict[str, dict[str, Any]]], report["metrics"])
    costs = make_subplots(
        rows=2,
        cols=3,
        subplot_titles=[f"{version} {probe}" for version in versions for probe in PROBES],
    )
    for index, (version, probe) in enumerate(
        (version, probe) for version in versions for probe in PROBES
    ):
        values = metrics[version][probe]
        initial, gross, final = map(float, (
            values["initial_nav"], values["gross_final_nav"], values["final_nav"]
        ))
        trace = go.Waterfall(
            x=["Initial", "Gross P&L", "Cost drag", "Final"],
            y=[initial, gross - initial, final - gross, final],
            measure=["absolute", "relative", "relative", "total"],
            name=f"{version} {probe}", showlegend=False,
        )
        costs.add_trace(trace, row=index // 3 + 1, col=index % 3 + 1)

    clusters = cast(list[dict[str, Any]], report["diffusing_cluster_vxz_vs_sgov"])
    cluster_figure = go.Figure()
    for version in versions:
        records = [record for record in clusters if record["weather_version"] == version]
        cluster_figure.add_trace(go.Bar(
            x=[f"{record['signal_start']} #{record['cluster_id']}" for record in records],
            y=[record["vxz_minus_sgov"] for record in records], name=version,
        ))
    cluster_figure.update_layout(barmode="group", yaxis_title="VXZ return minus SGOV return")
    return [
        (f"{'/'.join(versions)} 三个固定探针净值", nav),
        ("Underwater 回撤", underwater),
        ("滚动 20-session 收益", rolling),
        ("最差 20 个 SVXY 日的实际资产暴露", exposure),
        ("状态与 Combined 持仓时间轴", timeline),
        ("调仓、turnover 与成本瀑布", costs),
        ("每个 DIFFUSING 事件簇的 VXZ 相对 SGOV 收益", cluster_figure),
    ]


def _economic_report_html(ledger: pd.DataFrame, report: dict[str, Any]) -> str:
    versions = tuple(cast(list[str], report["comparison_versions"]))
    metrics = cast(dict[str, dict[str, dict[str, Any]]], report["metrics"])
    classifications = cast(dict[str, str], report["classifications"])
    metric_rows = []
    for probe in PROBES:
        for version in versions:
            values = metrics[version][probe]
            metric_rows.append(
                "<tr>"
                f"<td>{version}</td><td>{probe}</td>"
                f"<td>${values['final_nav']:,.2f}</td><td>{values['total_return']:.2%}</td>"
                f"<td>{values['max_drawdown']:.2%}</td>"
                f"<td>{values['worst_rolling_20d']:.2%}</td>"
                f"<td>{values['asset_switches']}</td><td>{values['total_turnover']:.1f}</td>"
                f"<td>${values['total_cost_paid']:,.2f}</td></tr>"
            )
    verdict_rows = "".join(
        f"<li><b>{probe}</b>: <code>{classification}</code></li>"
        for probe, classification in classifications.items()
    )
    chart_html = []
    for index, (title, figure) in enumerate(_economic_figures(ledger, report)):
        chart_html.append(
            f"<section><h2>{title}</h2>"
            + pio.to_html(
                figure,
                full_html=False,
                include_plotlyjs="inline" if index == 0 else False,
                config={"displaylogo": False, "responsive": True},
            )
            + "</section>"
        )
    source = cast(dict[str, Any], report["price_source"])
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MatVIX {'/'.join(versions)} Frozen Economic Probe</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#0b1220;color:#e5e7eb}}main{{max-width:1500px;margin:auto;padding:28px}}section{{background:#111827;border:1px solid #334155;border-radius:14px;margin:18px 0;padding:18px}}h1,h2{{color:#f8fafc}}code{{color:#fbbf24}}table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border-bottom:1px solid #334155;text-align:right}}th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}.boundary{{color:#fca5a5}}</style></head>
<body><main><h1>MatVIX {'/'.join(versions)} 冻结经济探针</h1>
<p class="boundary">固定研究探针，不是策略优化、生产绩效或交易许可。</p>
<section><h2>独立判定</h2><ul>{verdict_rows}</ul><p>综合结论：<code>{report['comprehensive_verdict']}</code></p></section>
<section><h2>审计指标</h2><table><thead><tr><th>版本</th><th>探针</th><th>终值</th><th>总收益</th><th>最大回撤</th><th>最差20日</th><th>切换</th><th>Turnover</th><th>成本</th></tr></thead><tbody>{''.join(metric_rows)}</tbody></table></section>
<section><h2>数据合同</h2><p>Yahoo Finance Chart JSON API batch <code>{source['batch_id']}</code>；共同区间 {report['common_range']['first_signal_session']} 至 {report['common_range']['last_return_through_session']}；初始资金 $10,000；单边成本 5bp；t+1 adjusted open 执行。</p></section>
{''.join(chart_html)}
</main></body></html>"""


def write_economic_probe_outputs(
    ledger: pd.DataFrame, report: dict[str, Any], project_root: str | Path,
    *, output_version: str = "v2", refuse_existing: bool = False,
) -> dict[str, Path]:
    output_dir = Path(project_root).resolve() / "outputs" / f"{output_version}_economic_probe"
    ledger_path = output_dir / "daily_ledger.csv"
    report_path = output_dir / "report.json"
    html_path = output_dir / "report.html"
    if refuse_existing and any(path.exists() for path in (ledger_path, report_path, html_path)):
        raise FileExistsError("Frozen V3 economic probe output already exists; rerun forbidden")
    output_dir.mkdir(parents=True, exist_ok=True)
    _atomic_text(ledger.to_csv(index=False, date_format="%Y-%m-%dT%H:%M:%S%z"), ledger_path)
    write_json(report, report_path)
    _atomic_text(_economic_report_html(ledger, report), html_path)
    return {"ledger": ledger_path, "report": report_path, "html": html_path}


def build_v3_economic_probe(
    *, v2_states: pd.DataFrame, v3_states: pd.DataFrame, shadow_oof: pd.DataFrame,
    prices: pd.DataFrame, source_manifest: dict[str, Any], station_summary: dict[str, Any],
    replay_evidence: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    start = pd.Timestamp("2023-06-16")
    weather = {"V2": adapt_weather(v2_states, "V2"),
               "V3": build_v3_adapter(v3_states, shadow_oof)}
    weather = {name: frame.loc[frame["session_date"].ge(start)].copy() for name, frame in weather.items()}
    aligned = weather["V2"][["session_date", "base_short_allowed"]].merge(
        weather["V3"][["session_date", "short_allowed_v3"]], on="session_date", how="inner"
    )
    if (aligned["short_allowed_v3"] & ~aligned["base_short_allowed"]).any():
        raise ValueError("V3 shadow would add Short exposure relative to frozen V2")
    ledger, report = _build_economic_comparison(
        weather=weather, prices=prices, source_manifest=source_manifest,
        station_summary=station_summary, v3_contract=True,
    )
    report.update({"adapter_spec_id": SPEC_ID, "adapter_spec_sha256": SPEC_SHA256,
        "fragility_replay_evidence": replay_evidence,
        "historical_evidence_class": (
            "HISTORICAL_RESEARCH_SUPPORT"
            if report["comprehensive_verdict"] == "COMPREHENSIVE_POSITIVE"
            else "NO_COMPREHENSIVE_INCREMENT"
        ),
        "production_promotion": False})
    return ledger, report


def run_frozen_v3_economic_probe(
    *, project_root: str | Path, v2_states: pd.DataFrame, v3_states: pd.DataFrame,
    station_summary: dict[str, Any],
) -> tuple[dict[str, Path], dict[str, Any]]:
    root = Path(project_root).resolve()
    output_dir = root / "outputs" / "v3_economic_probe"
    if any((output_dir / name).exists() for name in ("daily_ledger.csv", "report.json", "report.html")):
        raise FileExistsError("Frozen V3 economic probe output already exists; rerun forbidden")
    station_path = root / "outputs" / "v3_station_acceptance" / "summary.json"
    if hashlib.sha256(station_path.read_bytes()).hexdigest() != V3_STAGE_D_SHA256:
        raise ValueError("V3 Stage-D summary digest differs from the frozen adapter contract")
    if station_summary.get("economic_probe_entry", {}).get("status") != "PASS":
        raise ValueError("V3 economic probe is blocked by Stage-D entry")
    shadow_oof, replay = verify_frozen_replay(v3_states)
    manifest_path = root / "data" / "raw" / "economic_probe" / "20260822T093334.462165Z" / "manifest.json"
    prices, source_manifest = _load_price_batch(manifest_path, root)
    source_manifest["frozen_manifest_path"] = str(manifest_path.relative_to(root))
    ledger, report = build_v3_economic_probe(
        v2_states=v2_states, v3_states=v3_states, shadow_oof=shadow_oof,
        prices=prices, source_manifest=source_manifest, station_summary=station_summary,
        replay_evidence=replay,
    )
    outputs = write_economic_probe_outputs(
        ledger, report, root, output_version="v3", refuse_existing=True)
    return outputs, report


def run_frozen_economic_probe(
    *,
    project_root: str | Path,
    v1_states: pd.DataFrame,
    v2_states: pd.DataFrame,
    station_summary: dict[str, Any],
) -> tuple[dict[str, Path], dict[str, Any]]:
    first_session = pd.Timestamp("2020-05-20")
    last_session = min(
        pd.Timestamp(v1_states["session_date"].max()).normalize(),
        pd.Timestamp(v2_states["session_date"].max()).normalize(),
    )
    prices, source_manifest = fetch_yahoo_price_batch(
        project_root, first_session=first_session, last_session=last_session
    )
    ledger, report = build_economic_probe(
        v1_states=v1_states,
        v2_states=v2_states,
        prices=prices,
        source_manifest=source_manifest,
        station_summary=station_summary,
    )
    return write_economic_probe_outputs(ledger, report, project_root), report

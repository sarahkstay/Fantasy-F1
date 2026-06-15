"""Read-side helpers for the visitor "follow the season" experience.

All inputs come from files the owner wizard writes:
  - data/fantasy/history.csv — one row per locked-in round (the model team)
  - data/fantasy/results/round_NN_race.csv — official race results
  - data/fantasy/competitors.csv (optional) — points for the human + pure-AI teams

Functions here are pure (no Streamlit calls) so they're testable.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


THREE_TEAM_LABELS = {
    "human": "Pure human judgement",
    "claude_chat": "Pure-AI Claude chat",
    "model": "Vibe-coded data science model",
}


def competitors_path(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "fantasy" / "competitors.csv"


def chips_path(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "fantasy" / "chips.csv"


def breakdowns_path(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "fantasy" / "breakdowns.csv"


_BREAKDOWN_COLS = ["round", "team_key", "asset", "name", "kind", "points"]


def load_breakdowns(project_root: str | Path) -> pd.DataFrame:
    p = breakdowns_path(project_root)
    if not p.exists():
        return pd.DataFrame(columns=_BREAKDOWN_COLS)
    return pd.read_csv(p)


def append_breakdown(
    project_root: str | Path,
    round_number: int,
    team_key: str,
    rows: list[dict[str, Any]],
) -> Path:
    """Insert/replace breakdown rows for one (round, team_key)."""
    p = breakdowns_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    df = load_breakdowns(project_root)

    if not df.empty:
        mask = (df["round"].astype(int) == int(round_number)) & (
            df["team_key"].astype(str) == team_key
        )
        df = df[~mask]

    if rows:
        new_df = pd.DataFrame([
            {
                "round": int(round_number),
                "team_key": team_key,
                "asset": r["asset"],
                "name": r["name"],
                "kind": r["kind"],
                "points": round(float(r["points"]), 2),
            }
            for r in rows
        ])
        df = pd.concat([df, new_df], ignore_index=True)

    df = df.sort_values(["round", "team_key", "kind", "asset"]).reset_index(drop=True)
    df.to_csv(p, index=False)
    return p


def history_path(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "fantasy" / "history.csv"


def race_result_path(project_root: str | Path, round_number: int) -> Path:
    return Path(project_root) / "data" / "fantasy" / "results" / f"round_{int(round_number):02d}_race.csv"


def load_history(project_root: str | Path) -> pd.DataFrame:
    p = history_path(project_root)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def load_competitor_history(project_root: str | Path) -> pd.DataFrame:
    """Returns a long-form df: round, team_key, team_name, points."""
    p = competitors_path(project_root)
    if not p.exists():
        return pd.DataFrame(columns=["round", "team_key", "team_name", "points"])
    df = pd.read_csv(p)
    if "team_name" not in df.columns and "team_key" in df.columns:
        df["team_name"] = df["team_key"].map(THREE_TEAM_LABELS).fillna(df["team_key"])
    return df


def load_chip_usage(project_root: str | Path) -> pd.DataFrame:
    """Long-form team metadata log: round, team_key, chip, details, drs_boost."""
    p = chips_path(project_root)
    if not p.exists():
        return pd.DataFrame(columns=["round", "team_key", "team_name", "chip", "details", "drs_boost"])
    try:
        df = pd.read_csv(p)
    except pd.errors.ParserError:
        # Fail-open in UI: keep app usable even if a row in chips.csv is malformed.
        df = pd.read_csv(p, engine="python", on_bad_lines="skip")
    if "team_name" not in df.columns and "team_key" in df.columns:
        df["team_name"] = df["team_key"].map(THREE_TEAM_LABELS).fillna(df["team_key"])
    if "details" not in df.columns:
        df["details"] = ""
    if "drs_boost" not in df.columns:
        df["drs_boost"] = ""
    return df


def append_chip_usage(
    project_root: str | Path,
    round_number: int,
    team_key: str,
    chip: str | None,
    details: str = "",
    drs_boost: str | None = None,
    team_name: str | None = None,
) -> Path:
    """Insert/replace metadata for (round, team_key); clears row if chip+drs are empty."""
    p = chips_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        df = pd.read_csv(p)
    else:
        df = pd.DataFrame(columns=["round", "team_key", "team_name", "chip", "details", "drs_boost"])
    if "drs_boost" not in df.columns:
        df["drs_boost"] = ""

    if not df.empty:
        mask = (df["round"].astype(int) == int(round_number)) & (df["team_key"].astype(str) == str(team_key))
        df = df[~mask]

    chip_clean = str(chip or "").strip()
    drs_clean = str(drs_boost or "").strip().upper()
    has_chip = bool(chip_clean and chip_clean.lower() != "none")
    has_drs = bool(drs_clean)
    if has_chip or has_drs:
        name = team_name or THREE_TEAM_LABELS.get(team_key, team_key)
        df = pd.concat(
            [
                df,
                pd.DataFrame(
                    [
                        {
                            "round": int(round_number),
                            "team_key": str(team_key),
                            "team_name": str(name),
                            "chip": chip_clean if has_chip else "",
                            "details": str(details or ""),
                            "drs_boost": drs_clean,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    if not df.empty:
        df = df.sort_values(["round", "team_key"]).reset_index(drop=True)
    df.to_csv(p, index=False)
    return p


def latest_round_in_history(project_root: str | Path) -> int | None:
    df = load_history(project_root)
    if df.empty or "round" not in df.columns:
        return None
    return int(df["round"].astype(int).max())


def cumulative_points_by_team(project_root: str | Path) -> pd.DataFrame:
    """Long-form: round, team_key, team_name, cumulative_points.

    Combines model team (from history.csv `actual_points`) with competitors.csv.
    History is the source of truth for `model`; any `model` row in
    competitors.csv that overlaps with history is skipped to prevent duplicates
    (Altair would sum them as stacked bars).
    """
    rows: list[dict[str, Any]] = []
    rounds_from_history_by_team: dict[str, set[int]] = {}
    last_cumulative_by_team: dict[str, float] = {}

    hist = load_history(project_root)
    if not hist.empty and "actual_points" in hist.columns:
        h = hist.copy()
        h["actual_points"] = pd.to_numeric(h["actual_points"], errors="coerce").fillna(0.0)
        h = h.sort_values("round")
        h["cumulative_points"] = h["actual_points"].cumsum()
        for _, r in h.iterrows():
            rows.append({
                "round": int(r["round"]),
                "team_key": "model",
                "team_name": THREE_TEAM_LABELS["model"],
                "cumulative_points": float(r["cumulative_points"]),
                "round_points": float(r["actual_points"]),
            })
            rounds_from_history_by_team.setdefault("model", set()).add(int(r["round"]))
            last_cumulative_by_team["model"] = float(r["cumulative_points"])

    comp = load_competitor_history(project_root)
    if not comp.empty:
        comp["points"] = pd.to_numeric(comp["points"], errors="coerce").fillna(0.0)
        # Drop overlaps for any team already represented in history.
        for tk, rounds_seen in rounds_from_history_by_team.items():
            if not rounds_seen:
                continue
            mask = (comp["team_key"] == tk) & (comp["round"].astype(int).isin(rounds_seen))
            comp = comp[~mask]

        comp = comp.sort_values(["team_key", "round"])
        for team_key, grp in comp.groupby("team_key", sort=False):
            base = float(last_cumulative_by_team.get(str(team_key), 0.0))
            running = base
            for _, r in grp.iterrows():
                running += float(r["points"])
                rows.append(
                    {
                        "round": int(r["round"]),
                        "team_key": str(r["team_key"]),
                        "team_name": str(r["team_name"]),
                        "cumulative_points": float(running),
                        "round_points": float(r["points"]),
                    }
                )
            last_cumulative_by_team[str(team_key)] = float(running)

    return pd.DataFrame(rows)


def current_leaderboard(project_root: str | Path) -> pd.DataFrame:
    """Latest cumulative points per team, sorted descending."""
    cum = cumulative_points_by_team(project_root)
    if cum.empty:
        return pd.DataFrame(columns=["team_key", "team_name", "cumulative_points", "rank"])
    latest = cum.sort_values("round").groupby("team_key", as_index=False).tail(1)
    latest = latest.sort_values("cumulative_points", ascending=False).reset_index(drop=True)
    latest["rank"] = latest.index + 1
    return latest[["rank", "team_key", "team_name", "cumulative_points"]]


def transfer_log(project_root: str | Path) -> pd.DataFrame:
    """One row per team change: round, drivers_in, drivers_out, ctors_in, ctors_out, drs_boost."""
    hist = load_history(project_root)
    if hist.empty:
        return pd.DataFrame()
    hist = hist.sort_values("round").reset_index(drop=True)
    rows = []
    prev_drivers: set[str] = set()
    prev_ctors: set[str] = set()
    for _, r in hist.iterrows():
        d = set(str(r["drivers"]).split(",")) if pd.notna(r["drivers"]) else set()
        c = set(str(r["constructors"]).split(",")) if pd.notna(r["constructors"]) else set()
        if not prev_drivers and not prev_ctors:
            in_d, out_d, in_c, out_c = sorted(d), [], sorted(c), []
        else:
            in_d = sorted(d - prev_drivers)
            out_d = sorted(prev_drivers - d)
            in_c = sorted(c - prev_ctors)
            out_c = sorted(prev_ctors - c)
        rows.append({
            "round": int(r["round"]),
            "drivers_in": ", ".join(in_d) or "—",
            "drivers_out": ", ".join(out_d) or "—",
            "constructors_in": ", ".join(in_c) or "—",
            "constructors_out": ", ".join(out_c) or "—",
            "drs_boost": str(r.get("drs_boost", "") or ""),
            "chips_used": str(r.get("chips_used", "") or ""),
            "chip_details": str(r.get("chip_details", "") or ""),
            "actual_points": r.get("actual_points", ""),
            "notes": str(r.get("notes", "") or ""),
        })
        prev_drivers, prev_ctors = d, c
    return pd.DataFrame(rows)


def append_competitor_score(
    project_root: str | Path,
    round_number: int,
    team_key: str,
    points: float,
    team_name: str | None = None,
) -> Path:
    """Insert/replace one round-team-score row in competitors.csv.

    `team_key` should be one of the keys in THREE_TEAM_LABELS (e.g. "human",
    "claude_chat"). `team_name` defaults to the canonical label.
    """
    p = competitors_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    name = team_name or THREE_TEAM_LABELS.get(team_key, team_key)

    if p.exists():
        df = pd.read_csv(p)
    else:
        df = pd.DataFrame(columns=["round", "team_key", "team_name", "points"])

    # Replace existing row for (round, team_key)
    if not df.empty:
        mask = (df["round"].astype(int) == int(round_number)) & (df["team_key"].astype(str) == team_key)
        df = df[~mask]

    new_row = pd.DataFrame([{
        "round": int(round_number),
        "team_key": team_key,
        "team_name": name,
        "points": round(float(points), 2),
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values(["round", "team_key"]).reset_index(drop=True)
    df.to_csv(p, index=False)
    return p


def predictions_dir(project_root: str | Path) -> Path:
    return Path(project_root) / "data" / "fantasy" / "predictions"


def load_round_predictions(project_root: str | Path, round_number: int) -> pd.DataFrame:
    """Load saved predictions for one round (year+round+driver+constructor+y_pred)."""
    p = predictions_dir(project_root) / f"round_{int(round_number):02d}_predictions.csv"
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def _features_actuals(project_root: str | Path) -> pd.DataFrame:
    """Lazy-loaded features.parquet race rows (only the columns we need)."""
    p = Path(project_root) / "data" / "processed" / "features.parquet"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p, columns=["year", "round", "driver_code", "constructor_id", "session_type", "fantasy_points_driver"])
    return df[df["session_type"] == "race"]


def prediction_vs_actual(
    project_root: str | Path,
    round_number: int,
    features_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join saved predictions with features.parquet actuals for one round.

    Returns columns: round, driver_code, constructor_id, predicted, actual,
    error (actual - predicted), abs_error.
    """
    pred = load_round_predictions(project_root, round_number)
    if pred.empty:
        return pd.DataFrame()
    year = int(pred["year"].iloc[0])
    feats = features_df if features_df is not None else _features_actuals(project_root)
    if feats.empty:
        actuals = pd.DataFrame(columns=["driver_code", "constructor_id", "actual"])
    else:
        actuals = feats[(feats["year"] == year) & (feats["round"] == int(round_number))][
            ["driver_code", "constructor_id", "fantasy_points_driver"]
        ].rename(columns={"fantasy_points_driver": "actual"})
    df = pred.rename(columns={"y_pred": "predicted"}).merge(
        actuals, on=["driver_code", "constructor_id"], how="left"
    )
    df["actual"] = pd.to_numeric(df["actual"], errors="coerce").fillna(0.0)
    df["predicted"] = pd.to_numeric(df["predicted"], errors="coerce").fillna(0.0)
    df["error"] = df["actual"] - df["predicted"]
    df["abs_error"] = df["error"].abs()
    return df


def prediction_accuracy_over_time(project_root: str | Path) -> pd.DataFrame:
    """Aggregate prediction accuracy per round across all drivers.

    Returns columns: round, mae, n_drivers.
    """
    pdir = predictions_dir(project_root)
    if not pdir.exists():
        return pd.DataFrame(columns=["round", "mae", "n_drivers"])
    feats = _features_actuals(project_root)
    rows: list[dict[str, Any]] = []
    for p in sorted(pdir.glob("round_*_predictions.csv")):
        try:
            rnd = int(p.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        df = prediction_vs_actual(project_root, rnd, features_df=feats)
        if df.empty:
            continue
        rows.append({
            "round": rnd,
            "mae": float(df["abs_error"].mean()),
            "n_drivers": int(len(df)),
        })
    return pd.DataFrame(rows).sort_values("round").reset_index(drop=True) if rows else pd.DataFrame(columns=["round", "mae", "n_drivers"])


def driver_ownership_long(project_root: str | Path) -> pd.DataFrame:
    """Long-form: one row per (driver, round) the driver was on the model team.

    Powers the driver-tenure Gantt chart on the History page.
    """
    hist = load_history(project_root)
    if hist.empty:
        return pd.DataFrame(columns=["driver", "round"])
    rows: list[dict[str, Any]] = []
    for _, r in hist.iterrows():
        rnd_val = r.get("round")
        if pd.isna(rnd_val):
            continue
        rnd = int(rnd_val)
        for d in str(r.get("drivers", "")).split(","):
            d = d.strip()
            if d:
                rows.append({"driver": d, "round": rnd})
    return pd.DataFrame(rows)


def driver_tenure(project_root: str | Path) -> pd.DataFrame:
    """How many rounds each driver has been on the team."""
    hist = load_history(project_root)
    if hist.empty:
        return pd.DataFrame(columns=["driver", "rounds_owned", "first_round", "last_round"])
    counts: Counter[str] = Counter()
    first_round: dict[str, int] = {}
    last_round: dict[str, int] = {}
    for _, r in hist.sort_values("round").iterrows():
        rnd = int(r["round"])
        for d in str(r["drivers"]).split(","):
            d = d.strip()
            if not d:
                continue
            counts[d] += 1
            first_round.setdefault(d, rnd)
            last_round[d] = rnd
    rows = [
        {
            "driver": d,
            "rounds_owned": counts[d],
            "first_round": first_round[d],
            "last_round": last_round[d],
        }
        for d in counts
    ]
    return pd.DataFrame(rows).sort_values("rounds_owned", ascending=False).reset_index(drop=True)

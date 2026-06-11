from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class FileHealth:
    path: str
    exists: bool
    mtime: float | None
    size_bytes: int | None


def _file_health(path: str | Path) -> FileHealth:
    p = Path(path)
    if not p.exists():
        return FileHealth(path=str(p), exists=False, mtime=None, size_bytes=None)
    stat = p.stat()
    return FileHealth(path=str(p), exists=True, mtime=stat.st_mtime, size_bytes=stat.st_size)


def collect_health_checks(project_root: str | Path = ".") -> dict[str, FileHealth]:
    root = Path(project_root)
    targets = {
        "features": root / "data/processed/features.parquet",
        "model": root / "data/processed/models/fantasy_model.joblib",
        "predictions_dir": root / "data/processed/predictions",
        "kpi_png": root / "data/processed/optimizer_reports/kpi_dashboard.png",
        "strict_summary": root / "data/processed/optimizer_tuning_strict_weight/optimizer_tuning_best_summary.json",
        "weight_sweep_csv": root / "data/processed/optimizer_reports/price_weight_sweep_2025.csv",
    }
    return {k: _file_health(v) for k, v in targets.items()}


def load_csv_if_exists(path: str | Path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def load_json_if_exists(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    import json

    return json.loads(p.read_text())


def load_analytics_bundle(project_root: str | Path = ".") -> dict[str, Any]:
    root = Path(project_root)
    return {
        "kpi_summary": load_csv_if_exists(root / "data/processed/optimizer_reports/kpi_summary.csv"),
        "strict_tuning_train": load_csv_if_exists(root / "data/processed/optimizer_tuning_strict_weight/optimizer_tuning_train_results.csv"),
        "strict_tuning_summary": load_json_if_exists(root / "data/processed/optimizer_tuning_strict_weight/optimizer_tuning_best_summary.json"),
        "price_weight_sweep": load_csv_if_exists(root / "data/processed/optimizer_reports/price_weight_sweep_2025.csv"),
        "health": collect_health_checks(root),
    }


def build_competitive_diagnostics(
    project_root: str | Path = ".",
    calendar: dict[Any, Any] | None = None,
    sprint_rounds: set[int] | None = None,
) -> dict[str, Any]:
    """Analyze model performance gap vs human and Claude teams by round.

    Returns:
      - round_diagnostics: DataFrame with per-round gaps and tagged causes
      - latest: dict with current cumulative gaps
      - highlights: list[str] quick readouts for UI
    """
    from src.ui_services.calendar_service import format_round_label
    from src.ui_services.season_service import cumulative_points_by_team, load_chip_usage

    sprint_rounds = sprint_rounds or set()
    cal = calendar or {}
    cum = cumulative_points_by_team(project_root)
    if cum.empty:
        return {"round_diagnostics": pd.DataFrame(), "latest": {}, "highlights": []}

    piv_round = (
        cum.pivot_table(index="round", columns="team_key", values="round_points", aggfunc="last")
        .reset_index()
        .sort_values("round")
    )
    piv_cum = (
        cum.pivot_table(index="round", columns="team_key", values="cumulative_points", aggfunc="last")
        .reset_index()
        .sort_values("round")
    )
    if "model" not in piv_round.columns:
        return {"round_diagnostics": pd.DataFrame(), "latest": {}, "highlights": []}

    out = piv_round.copy()
    out["model_points"] = pd.to_numeric(out.get("model"), errors="coerce").fillna(0.0)
    out["human_points"] = pd.to_numeric(out.get("human"), errors="coerce").fillna(0.0)
    out["claude_points"] = pd.to_numeric(out.get("claude_chat"), errors="coerce").fillna(0.0)
    out["delta_vs_human"] = out["model_points"] - out["human_points"]
    out["delta_vs_claude"] = out["model_points"] - out["claude_points"]
    out["sprint_round"] = out["round"].astype(int).isin({int(r) for r in sprint_rounds})
    out["race"] = out["round"].astype(int).apply(
        lambda r: format_round_label(cal, r, short=True) if cal else f"R{r}"
    )

    chips = load_chip_usage(project_root)
    chip_lookup: dict[tuple[int, str], str] = {}
    drs_lookup: dict[tuple[int, str], str] = {}
    if not chips.empty:
        c = chips.copy()
        c["round"] = pd.to_numeric(c["round"], errors="coerce").fillna(0).astype(int)
        c["chip"] = c.get("chip", "").fillna("").astype(str).str.strip()
        c["drs_boost"] = c.get("drs_boost", "").fillna("").astype(str).str.upper().str.strip()
        for _, row in c.iterrows():
            chip_lookup[(int(row["round"]), str(row.get("team_key", "")))] = str(row["chip"] or "")
            drs_lookup[(int(row["round"]), str(row.get("team_key", "")))] = str(row["drs_boost"] or "")

    out["model_chip"] = out["round"].astype(int).apply(lambda r: chip_lookup.get((int(r), "model"), ""))
    out["human_chip"] = out["round"].astype(int).apply(lambda r: chip_lookup.get((int(r), "human"), ""))
    out["claude_chip"] = out["round"].astype(int).apply(lambda r: chip_lookup.get((int(r), "claude_chat"), ""))
    out["model_drs"] = out["round"].astype(int).apply(lambda r: drs_lookup.get((int(r), "model"), ""))
    out["human_drs"] = out["round"].astype(int).apply(lambda r: drs_lookup.get((int(r), "human"), ""))
    out["claude_drs"] = out["round"].astype(int).apply(lambda r: drs_lookup.get((int(r), "claude_chat"), ""))

    def _diagnose(row: pd.Series) -> str:
        reasons: list[str] = []
        if row.get("model_chip"):
            reasons.append(f"model chip: {row['model_chip']}")
        if row.get("human_chip"):
            reasons.append(f"human chip: {row['human_chip']}")
        if row.get("claude_chip"):
            reasons.append(f"claude chip: {row['claude_chip']}")
        drs_flags = [bool(row.get("model_drs")), bool(row.get("human_drs")), bool(row.get("claude_drs"))]
        if sum(1 for b in drs_flags if b) >= 2:
            reasons.append("multiple DRS multipliers active")
        if bool(row.get("sprint_round")):
            reasons.append("sprint volatility")
        margin_h = float(row.get("delta_vs_human", 0.0))
        margin_c = float(row.get("delta_vs_claude", 0.0))
        if margin_h <= -30 or margin_c <= -30:
            reasons.append("high downside round")
        elif margin_h >= 30 and margin_c >= 30:
            reasons.append("strong edge round")
        return "; ".join(reasons) if reasons else "normal variance"

    out["diagnosis"] = out.apply(_diagnose, axis=1)

    latest: dict[str, Any] = {}
    if not piv_cum.empty:
        lr = piv_cum.sort_values("round").iloc[-1]
        latest = {
            "round": int(lr["round"]),
            "model_cumulative": float(pd.to_numeric(lr.get("model"), errors="coerce") or 0.0),
            "human_cumulative": float(pd.to_numeric(lr.get("human"), errors="coerce") or 0.0),
            "claude_cumulative": float(pd.to_numeric(lr.get("claude_chat"), errors="coerce") or 0.0),
        }
        latest["cum_gap_vs_human"] = latest["model_cumulative"] - latest["human_cumulative"]
        latest["cum_gap_vs_claude"] = latest["model_cumulative"] - latest["claude_cumulative"]

    last3 = out.sort_values("round").tail(3)
    highlights = []
    if not last3.empty:
        highlights.append(f"Last 3 rounds avg vs human: {last3['delta_vs_human'].mean():+.1f} pts/round")
        highlights.append(f"Last 3 rounds avg vs Claude: {last3['delta_vs_claude'].mean():+.1f} pts/round")
    spike = out.reindex(out["delta_vs_human"].abs().sort_values(ascending=False).index).head(1)
    if not spike.empty:
        s = spike.iloc[0]
        highlights.append(
            f"Biggest model-vs-human swing: {s['race']} ({float(s['delta_vs_human']):+.0f}) — {s['diagnosis']}"
        )

    keep_cols = [
        "round",
        "race",
        "model_points",
        "human_points",
        "claude_points",
        "delta_vs_human",
        "delta_vs_claude",
        "model_chip",
        "human_chip",
        "claude_chip",
        "model_drs",
        "human_drs",
        "claude_drs",
        "sprint_round",
        "diagnosis",
    ]
    return {"round_diagnostics": out[keep_cols], "latest": latest, "highlights": highlights}

"""CSV ingestion for the weekly owner workflow.

Parsers are lenient about column names (the user assembles CSVs by hand
via Perplexity / Comet) but strict about types after parsing.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class IngestResult:
    ok: bool
    rows: int = 0
    saved_path: str | None = None
    updated_config: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parsed: pd.DataFrame | None = None


def _parse_csv_text(text: str) -> pd.DataFrame | None:
    if not text or not text.strip():
        return None
    return pd.read_csv(StringIO(text.strip()))


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {c.lower().strip(): c for c in df.columns}
    for c in candidates:
        if c.lower() in lower_map:
            return lower_map[c.lower()]
    return None


# ---------------------------------------------------------------------------
# Price CSV ingest (drivers + constructors)
# ---------------------------------------------------------------------------

_DRIVER_CODE_COLS = ["code", "driver_code", "driver", "asset", "dr", "abbr", "name"]
_CTOR_CODE_COLS = ["code", "constructor_id", "constructor", "team", "team_id", "asset", "cr", "name"]
_PRICE_COLS = ["price", "value", "cost", "current_price", "price_million_usd", "price_usd", "price_m"]
_TYPE_COLS = ["type", "kind", "category", "asset_type"]
_DRIVER_TYPE_TOKENS = {"driver", "drivers"}
_CTOR_TYPE_TOKENS = {"constructor", "constructors", "team", "teams"}


def _filter_by_type(df: pd.DataFrame, want: str) -> pd.DataFrame:
    """If a type column exists, keep only rows matching `want` ('driver' or 'constructor').
    Returns df unchanged if no type column is present (so single-kind CSVs still work).
    """
    type_col = _find_col(df, _TYPE_COLS)
    if not type_col:
        return df
    keep = _DRIVER_TYPE_TOKENS if want == "driver" else _CTOR_TYPE_TOKENS
    mask = df[type_col].astype(str).str.strip().str.lower().isin(keep)
    return df[mask].reset_index(drop=True)


def ingest_driver_prices(cfg: dict[str, Any], csv_text: str) -> IngestResult:
    df = _parse_csv_text(csv_text)
    if df is None or df.empty:
        return IngestResult(ok=False, errors=["Driver prices CSV is empty"])

    df = _filter_by_type(df, "driver")
    if df.empty:
        return IngestResult(ok=True, rows=0, updated_config=cfg, warnings=["No driver rows found in CSV"])

    code_col = _find_col(df, _DRIVER_CODE_COLS)
    price_col = _find_col(df, _PRICE_COLS)
    if not code_col:
        return IngestResult(ok=False, errors=[f"Could not find driver code column. Got: {list(df.columns)}"])
    if not price_col:
        return IngestResult(ok=False, errors=[f"Could not find price column. Got: {list(df.columns)}"])

    out = copy.deepcopy(cfg)
    target = out.setdefault("prices", {}).setdefault("drivers", {})
    if not isinstance(target, dict):
        return IngestResult(ok=False, errors=["config.prices.drivers is not a dict"])

    driver_lookup = _build_driver_name_lookup(cfg)
    warnings: list[str] = []
    updated = 0
    for i, row in df.iterrows():
        raw = str(row[code_col]).strip()
        if not raw or raw.lower() == "nan":
            continue
        code = _resolve_driver(raw, driver_lookup) or raw.upper()
        if code not in target:
            warnings.append(f"Unknown driver '{raw}' — not in config.prices.drivers (skipped)")
            continue
        try:
            price = float(row[price_col])
        except (TypeError, ValueError):
            warnings.append(f"Invalid price for {code}: {row[price_col]!r}")
            continue
        target[code]["price"] = round(price, 3)
        updated += 1

    return IngestResult(ok=True, rows=updated, updated_config=out, warnings=warnings, parsed=df)


def ingest_constructor_prices(cfg: dict[str, Any], csv_text: str) -> IngestResult:
    df = _parse_csv_text(csv_text)
    if df is None or df.empty:
        return IngestResult(ok=False, errors=["Constructor prices CSV is empty"])

    df = _filter_by_type(df, "constructor")
    if df.empty:
        return IngestResult(ok=True, rows=0, updated_config=cfg, warnings=["No constructor rows found in CSV"])

    code_col = _find_col(df, _CTOR_CODE_COLS)
    price_col = _find_col(df, _PRICE_COLS)
    if not code_col:
        return IngestResult(ok=False, errors=[f"Could not find constructor column. Got: {list(df.columns)}"])
    if not price_col:
        return IngestResult(ok=False, errors=[f"Could not find price column. Got: {list(df.columns)}"])

    out = copy.deepcopy(cfg)
    target = out.setdefault("prices", {}).setdefault("constructors", {})
    if not isinstance(target, dict):
        return IngestResult(ok=False, errors=["config.prices.constructors is not a dict"])

    team_lookup = _build_team_name_lookup(cfg)
    warnings: list[str] = []
    updated = 0
    for i, row in df.iterrows():
        raw = str(row[code_col]).strip()
        if not raw or raw.lower() == "nan":
            continue
        cid = _resolve_team(raw, team_lookup)
        if cid is None or cid not in target:
            warnings.append(f"Unknown constructor '{raw}' — not in config.prices.constructors (skipped)")
            continue
        try:
            price = float(row[price_col])
        except (TypeError, ValueError):
            warnings.append(f"Invalid price for {cid}: {row[price_col]!r}")
            continue
        target[cid]["price"] = round(price, 3)
        updated += 1

    return IngestResult(ok=True, rows=updated, updated_config=out, warnings=warnings, parsed=df)


# ---------------------------------------------------------------------------
# Race + qualifying results ingest
# ---------------------------------------------------------------------------

_POS_COLS = ["position", "pos", "place", "finish", "finishing_position"]
_DRIVER_RES_COLS = ["driver_code", "driver", "code", "abbr", "name"]
_TEAM_RES_COLS = ["team", "constructor", "constructor_id", "team_id"]
_POINTS_COLS = ["points", "pts"]
_FL_COLS = ["fastest_lap", "fl", "fastest"]
_DOTD_COLS = ["dotd", "driver_of_the_day", "driver_of_day"]
_DNF_COLS = ["dnf", "retired", "out", "status", "time / retired", "time/retired", "time"]
_GAIN_COLS = ["positions_gained", "gained", "delta", "places_gained"]
_DNF_TOKENS = {"dnf", "retired", "ret", "dsq", "nc", "dq", "dns", "dnq"}
_Q1_COLS = ["q1", "sq1"]
_Q2_COLS = ["q2", "sq2"]
_Q3_COLS = ["q3", "sq3"]


def _time_to_ms(v: Any) -> float | None:
    """Parse lap time strings like 1:12.965 or 72.965 to milliseconds."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        if len(parts) == 2:
            mins, secs = parts
            try:
                return float(mins) * 60000.0 + float(secs) * 1000.0
            except ValueError:
                return None
    else:
        try:
            return float(s) * 1000.0
        except ValueError:
            return None
    return None


def _build_driver_name_lookup(cfg: dict[str, Any]) -> dict[str, str]:
    """Returns lowercased name fragment → driver code (e.g. {'antonelli': 'ANT', 'kimi antonelli': 'ANT'})."""
    out: dict[str, str] = {}
    for code, meta in (cfg.get("prices", {}).get("drivers", {}) or {}).items():
        full = str(meta.get("name", "")).strip()
        if not full:
            continue
        out[full.lower()] = code
        # Last name (handles "Antonelli", "Russell", "Hamilton")
        last = full.split()[-1].lower()
        out.setdefault(last, code)
        # Code itself, in case the CSV already uses codes
        out[code.lower()] = code
    return out


def _build_team_name_lookup(cfg: dict[str, Any]) -> dict[str, str]:
    """Returns lowercased name → constructor id (e.g. {'mercedes': 'mercedes', 'red bull': 'red_bull'})."""
    out: dict[str, str] = {}
    for cid, meta in (cfg.get("prices", {}).get("constructors", {}) or {}).items():
        out[cid.lower()] = cid
        out[cid.lower().replace("_", " ")] = cid  # 'red_bull' → 'red bull'
        full = str(meta.get("name", "")).strip()
        if full:
            out[full.lower()] = cid
            # Strip common suffix words ("Red Bull Racing" → "red bull")
            stripped = full.lower().replace(" racing", "").replace(" f1 team", "").strip()
            out.setdefault(stripped, cid)
    return out


def _resolve_driver(raw: str, lookup: dict[str, str]) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    if key in lookup:
        return lookup[key]
    # Try last word as last name
    last = key.split()[-1] if key.split() else key
    if last in lookup:
        return lookup[last]
    return None


_TEAM_SUFFIX_NOISE = (" f1 team", " formula one team", " racing", " grand prix")


def _resolve_team(raw: str, lookup: dict[str, str]) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    if key in lookup:
        return lookup[key]
    norm = key.replace("-", " ").replace("_", " ").strip()
    if norm in lookup:
        return lookup[norm]
    # Strip common suffixes from incoming value ("Haas F1 Team" → "haas")
    for suffix in _TEAM_SUFFIX_NOISE:
        if norm.endswith(suffix):
            stripped = norm[: -len(suffix)].strip()
            if stripped in lookup:
                return lookup[stripped]
    return None


@dataclass
class BreakdownRow:
    asset: str       # driver code (e.g. "RUS") or constructor id (e.g. "ferrari") or raw if unresolved
    name: str        # original label as pasted
    kind: str        # "driver" / "constructor" / "unknown"
    points: float


_BREAKDOWN_LINE_RE = re.compile(r"^(.+?)[\s,:|=]+(-?\d+(?:\.\d+)?)\s*(?:pts?|points?)?\s*$", re.IGNORECASE)


def parse_score_breakdown(
    text: str, cfg: dict[str, Any]
) -> tuple[list[BreakdownRow], float, list[str]]:
    """Parse a free-form per-driver / per-constructor score paste.

    Accepts lines like:
        "Bearman: -14"
        "Russell, 54"
        "Ferrari 75"
        "Racing Bulls = 18 pts"

    Returns (rows, total, warnings). Rows include unresolved entries (kind='unknown')
    so the user sees nothing silently dropped — but their points still count toward
    the total because the user pasted them with intent.
    """
    rows: list[BreakdownRow] = []
    total = 0.0
    warnings: list[str] = []
    if not text or not text.strip():
        return rows, total, warnings

    driver_lookup = _build_driver_name_lookup(cfg)
    team_lookup = _build_team_name_lookup(cfg)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _BREAKDOWN_LINE_RE.match(line)
        if not m:
            warnings.append(f"Couldn't parse line: {raw_line!r}")
            continue
        label = m.group(1).strip()
        try:
            pts = float(m.group(2))
        except ValueError:
            warnings.append(f"Bad number on line: {raw_line!r}")
            continue

        code = _resolve_driver(label, driver_lookup)
        if code:
            rows.append(BreakdownRow(asset=code, name=label, kind="driver", points=pts))
            total += pts
            continue
        tid = _resolve_team(label, team_lookup)
        if tid:
            rows.append(BreakdownRow(asset=tid, name=label, kind="constructor", points=pts))
            total += pts
            continue
        warnings.append(f"Unknown driver/team on line: {label!r} (still added to total)")
        rows.append(BreakdownRow(asset=label.lower(), name=label, kind="unknown", points=pts))
        total += pts

    return rows, total, warnings


def _normalize_results_df(
    df: pd.DataFrame, kind: str, cfg: dict[str, Any] | None = None
) -> tuple[pd.DataFrame, list[str]]:
    """Standardize result columns to: position, driver_code, team_id, points, fastest_lap, dotd, dnf, gained.

    When `cfg` is provided, driver names and team display names are resolved
    against `prices.drivers` / `prices.constructors`, so a CSV with values like
    "Antonelli" / "Mercedes" is mapped to "ANT" / "mercedes".
    """
    warnings: list[str] = []
    pos = _find_col(df, _POS_COLS)
    drv = _find_col(df, _DRIVER_RES_COLS)
    if not pos or not drv:
        raise ValueError(
            f"{kind}: required columns missing. Need position + driver. Got: {list(df.columns)}"
        )

    driver_lookup = _build_driver_name_lookup(cfg) if cfg else {}
    team_lookup = _build_team_name_lookup(cfg) if cfg else {}

    out = pd.DataFrame()
    out["position"] = pd.to_numeric(df[pos], errors="coerce").astype("Int64")

    raw_drivers = df[drv].astype(str).str.strip()
    if driver_lookup:
        resolved = raw_drivers.apply(lambda x: _resolve_driver(x, driver_lookup))
        unresolved = raw_drivers[resolved.isna()].tolist()
        if unresolved:
            warnings.append(
                f"{kind}: could not resolve driver(s): {', '.join(sorted(set(unresolved)))} — left blank"
            )
        out["driver_code"] = resolved.fillna("").astype(str)
    else:
        out["driver_code"] = raw_drivers.str.upper()

    team_col = _find_col(df, _TEAM_RES_COLS)
    if team_col:
        raw_teams = df[team_col].astype(str).str.strip()
        if team_lookup:
            resolved_t = raw_teams.apply(lambda x: _resolve_team(x, team_lookup))
            unresolved_t = raw_teams[resolved_t.isna()].tolist()
            if unresolved_t:
                warnings.append(
                    f"{kind}: could not resolve team(s): {', '.join(sorted(set(unresolved_t)))} — left blank"
                )
            out["team_id"] = resolved_t.fillna("").astype(str)
        else:
            out["team_id"] = (
                raw_teams.str.lower().str.replace(" ", "_").str.replace("-", "_")
            )
    else:
        out["team_id"] = pd.NA
        warnings.append(f"{kind}: no team column found — team_id left blank")

    fl = _find_col(df, _FL_COLS)
    out["fastest_lap"] = df[fl].astype(bool) if fl else False

    dotd = _find_col(df, _DOTD_COLS)
    out["dotd"] = df[dotd].astype(bool) if dotd else False

    dnf = _find_col(df, _DNF_COLS)
    if dnf:
        s = df[dnf].astype(str).str.lower()
        out["dnf"] = s.apply(lambda v: any(tok in v for tok in _DNF_TOKENS))
    else:
        out["dnf"] = False

    pts = _find_col(df, _POINTS_COLS)
    if pts:
        out["points"] = pd.to_numeric(df[pts], errors="coerce")
    else:
        # Don't fake a fantasy-points number from position alone — the real
        # rules (grid delta, overtakes, fastest lap, DOTD, constructor Q2/Q3)
        # need richer inputs. Leave blank; the Score Round page asks for the
        # official team total + optional breakdown instead.
        out["points"] = pd.NA

    gain = _find_col(df, _GAIN_COLS)
    out["positions_gained"] = pd.to_numeric(df[gain], errors="coerce") if gain else pd.NA

    # Preserve qualifying timing columns when present (Q1/Q2/Q3 or SQ1/SQ2/SQ3).
    if kind in {"qualifying", "sprint qualifying"}:
        q1 = _find_col(df, _Q1_COLS)
        q2 = _find_col(df, _Q2_COLS)
        q3 = _find_col(df, _Q3_COLS)
        out["q1_time_ms"] = df[q1].apply(_time_to_ms) if q1 else pd.NA
        out["q2_time_ms"] = df[q2].apply(_time_to_ms) if q2 else pd.NA
        out["q3_time_ms"] = df[q3].apply(_time_to_ms) if q3 else pd.NA

    out = out[out["driver_code"].astype(str).str.len() > 0]
    return out, warnings


def _save_results_csv(df: pd.DataFrame, project_root: Path, round_number: int, kind: str) -> Path:
    out_dir = project_root / "data" / "fantasy" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"round_{int(round_number):02d}_{kind}.csv"
    df.to_csv(out_path, index=False)
    return out_path


def save_price_snapshot(
    csv_text: str,
    project_root: str | Path,
    round_number: int,
    kind: str,
) -> Path | None:
    """Archive the raw uploaded prices CSV to data/fantasy/prices/round_NN_{kind}.csv.

    `kind` is "drivers" or "constructors". Returns None for empty input.
    """
    if not csv_text or not csv_text.strip():
        return None
    out_dir = Path(project_root) / "data" / "fantasy" / "prices"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"round_{int(round_number):02d}_{kind}.csv"
    out_path.write_text(csv_text)
    return out_path


def ingest_race_results(
    csv_text: str,
    project_root: str | Path,
    round_number: int,
    cfg: dict[str, Any] | None = None,
) -> IngestResult:
    df = _parse_csv_text(csv_text)
    if df is None or df.empty:
        return IngestResult(ok=False, errors=["Race results CSV is empty"])
    try:
        cleaned, warnings = _normalize_results_df(df, "race", cfg=cfg)
    except ValueError as e:
        return IngestResult(ok=False, errors=[str(e)])
    saved = _save_results_csv(cleaned, Path(project_root), round_number, "race")
    return IngestResult(ok=True, rows=len(cleaned), saved_path=str(saved), warnings=warnings, parsed=cleaned)


def ingest_qualifying_results(
    csv_text: str,
    project_root: str | Path,
    round_number: int,
    cfg: dict[str, Any] | None = None,
) -> IngestResult:
    df = _parse_csv_text(csv_text)
    if df is None or df.empty:
        return IngestResult(ok=False, errors=["Qualifying results CSV is empty"])
    try:
        cleaned, warnings = _normalize_results_df(df, "qualifying", cfg=cfg)
    except ValueError as e:
        return IngestResult(ok=False, errors=[str(e)])
    saved = _save_results_csv(cleaned, Path(project_root), round_number, "qualifying")
    return IngestResult(ok=True, rows=len(cleaned), saved_path=str(saved), warnings=warnings, parsed=cleaned)


def ingest_sprint_results(
    csv_text: str,
    project_root: str | Path,
    round_number: int,
    cfg: dict[str, Any] | None = None,
) -> IngestResult:
    df = _parse_csv_text(csv_text)
    if df is None or df.empty:
        return IngestResult(ok=False, errors=["Sprint results CSV is empty"])
    try:
        cleaned, warnings = _normalize_results_df(df, "sprint", cfg=cfg)
    except ValueError as e:
        return IngestResult(ok=False, errors=[str(e)])
    saved = _save_results_csv(cleaned, Path(project_root), round_number, "sprint")
    return IngestResult(ok=True, rows=len(cleaned), saved_path=str(saved), warnings=warnings, parsed=cleaned)


def ingest_sprint_qualifying_results(
    csv_text: str,
    project_root: str | Path,
    round_number: int,
    cfg: dict[str, Any] | None = None,
) -> IngestResult:
    df = _parse_csv_text(csv_text)
    if df is None or df.empty:
        return IngestResult(ok=False, errors=["Sprint qualifying results CSV is empty"])
    try:
        cleaned, warnings = _normalize_results_df(df, "sprint qualifying", cfg=cfg)
    except ValueError as e:
        return IngestResult(ok=False, errors=[str(e)])
    saved = _save_results_csv(cleaned, Path(project_root), round_number, "sprint_qualifying")
    return IngestResult(ok=True, rows=len(cleaned), saved_path=str(saved), warnings=warnings, parsed=cleaned)


# ---------------------------------------------------------------------------
# Per-team-points helper (computes what the user's locked-in team scored)
# ---------------------------------------------------------------------------


def compute_team_points_for_round(
    project_root: str | Path,
    round_number: int,
    drivers: list[str],
    constructors: list[str],
    drs_boost: str | None,
) -> dict[str, Any]:
    """Compute team driver points for a given round from saved session CSVs.

    Includes any available session files for the round:
      - race
      - sprint
      - qualifying
      - sprint_qualifying

    The helper sums per-driver points across those sessions exactly as stored in
    the ingested files. It does NOT apply extra DRS doubling, because Score Round
    totals are already entered from the official game output.
    Returns {} if no session file exists for that round.
    """
    root = Path(project_root)
    results_dir = root / "data" / "fantasy" / "results"
    session_files: list[tuple[str, Path]] = [
        ("race", results_dir / f"round_{int(round_number):02d}_race.csv"),
        ("sprint", results_dir / f"round_{int(round_number):02d}_sprint.csv"),
        ("qualifying", results_dir / f"round_{int(round_number):02d}_qualifying.csv"),
        ("sprint_qualifying", results_dir / f"round_{int(round_number):02d}_sprint_qualifying.csv"),
    ]
    existing = [(name, p) for name, p in session_files if p.exists()]
    if not existing:
        return {}

    session_points: dict[str, dict[str, float]] = {}
    for name, p in existing:
        df = pd.read_csv(p)
        if "driver_code" not in df.columns:
            continue
        pts_col = "points" if "points" in df.columns else None
        if pts_col is None:
            continue
        parsed = df[["driver_code", pts_col]].copy()
        parsed["driver_code"] = parsed["driver_code"].astype(str).str.upper().str.strip()
        parsed["points"] = pd.to_numeric(parsed[pts_col], errors="coerce").fillna(0.0)
        parsed = parsed[parsed["driver_code"].str.len() > 0]
        by_driver = parsed.groupby("driver_code", as_index=True)["points"].sum().to_dict()
        session_points[name] = {str(k): float(v) for k, v in by_driver.items()}

    rows = []
    total = 0.0
    drs = (drs_boost or "").upper()
    for code in [str(d).upper() for d in drivers]:
        race_pts = float(session_points.get("race", {}).get(code, 0.0))
        sprint_pts = float(session_points.get("sprint", {}).get(code, 0.0))
        quali_pts = float(session_points.get("qualifying", {}).get(code, 0.0))
        sprint_quali_pts = float(session_points.get("sprint_qualifying", {}).get(code, 0.0))
        weekend_base = race_pts + sprint_pts + quali_pts + sprint_quali_pts
        pts = weekend_base
        total += pts
        rows.append({
            "driver": code,
            "race_points": race_pts,
            "sprint_points": sprint_pts,
            "qualifying_points": quali_pts,
            "sprint_qualifying_points": sprint_quali_pts,
            "weekend_points_before_drs": weekend_base,
            "points": pts,
            "drs_doubled": False,
            "drs_selected_driver": code == drs,
        })
    return {
        "round": int(round_number),
        "drivers": rows,
        "constructors": [str(c).lower() for c in constructors],
        "total_driver_points": total,
        "session_results_paths": {name: str(p) for name, p in existing},
    }

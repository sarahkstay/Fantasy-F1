from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.components import inject_theme
from frontend.state import (
    get_working_config,
    github_settings_from_secrets,
    is_owner,
    require_auth,
)
from src.ui_services import (
    THREE_TEAM_LABELS,
    append_chip_usage,
    append_breakdown,
    append_lockin,
    append_competitor_score,
    calendar_rounds,
    format_round_label,
    history_path,
    ingest_qualifying_results,
    ingest_race_results,
    ingest_sprint_qualifying_results,
    ingest_sprint_results,
    is_cancelled,
    load_chip_usage,
    load_competitor_history,
    load_history,
    parse_score_breakdown,
    previous_active_round,
    propose_files_pr,
    update_actual_points,
    update_lockin_metadata,
)
from src.ui_services.season_service import breakdowns_path
from src.ui_services.season_service import chips_path
from src.ui_services.season_service import competitors_path


require_auth()

if not is_owner():
    inject_theme()
    st.title("Score Round")
    st.warning("This page is for the team principal only. Switch to **Performance** in the sidebar to follow the season.")
    st.stop()

inject_theme()

st.title("Score round")
st.caption("After each race: enter what each of the three teams actually scored. Powers the leaderboard + charts.")


# ---------------------------------------------------------------------------
# Round selector
# ---------------------------------------------------------------------------
cfg = get_working_config()
season = cfg.get("season", {})
calendar = season.get("calendar", {})
weather = cfg.get("weather_override", {})
hist = load_history(PROJECT_ROOT)
comp_df = load_competitor_history(PROJECT_ROOT)


def _is_round_fully_scored(round_num: int) -> bool:
    # Model team score exists in history.csv as actual_points
    model_scored = False
    if not hist.empty:
        rows = hist[hist["round"].astype(int) == int(round_num)]
        if not rows.empty:
            val = rows.iloc[0].get("actual_points", "")
            try:
                model_scored = str(val).strip() not in {"", "nan"} and pd.notna(float(val))
            except (TypeError, ValueError):
                model_scored = False

    # Human + Claude scores exist in competitors.csv
    human_scored = False
    claude_scored = False
    if not comp_df.empty:
        crows = comp_df[comp_df["round"].astype(int) == int(round_num)]
        if not crows.empty:
            keys = set(crows["team_key"].astype(str))
            human_scored = "human" in keys
            claude_scored = "claude_chat" in keys

    return model_scored and human_scored and claude_scored

st.header("1. Pick the round")
all_rounds = calendar_rounds(calendar, include_cancelled=True) or list(range(1, int(season.get("total_rounds", 24)) + 1))
active_rounds = [r for r in all_rounds if not is_cancelled(calendar, int(r))]
next_unscored = next((int(r) for r in active_rounds if not _is_round_fully_scored(int(r))), None)
if next_unscored is None:
    next_unscored = previous_active_round(calendar, int(weather.get("next_race_round", 1)))
try:
    default_index = all_rounds.index(next_unscored)
except ValueError:
    default_index = 0
round_number = st.selectbox(
    "Round to score",
    options=all_rounds,
    index=default_index,
    format_func=lambda r: format_round_label(calendar, r),
    help="Defaults to the next unscored active round. Cancelled rounds stay listed but flagged.",
)

# ---------------------------------------------------------------------------
# Optional session-results ingest (for backfilling past rounds)
# ---------------------------------------------------------------------------
st.header("1b. Optional: paste/import session results for this round")
st.caption(
    "Use this when backfilling old rounds. These files feed retraining and weekly scoring context."
)


def _csv_input(label: str, key: str, placeholder: str) -> str:
    upload = st.file_uploader(f"Upload {label} CSV", type=["csv"], key=f"{key}_file")
    pasted = st.text_area(
        f"…or paste {label} CSV",
        key=f"{key}_paste",
        height=150,
        placeholder=placeholder,
    )
    if upload is not None:
        return upload.getvalue().decode("utf-8")
    return pasted


_RACE_EXAMPLE = (
    "POS,NO,DRIVER,TEAM,LAPS,TIME / RETIRED,PTS\n"
    "1,12,Antonelli,Mercedes,56,1:33:15.607,25\n"
    "2,63,Russell,Mercedes,56,+5.515s,18\n"
    "3,44,Hamilton,Ferrari,56,+25.267s,15"
)
_QUALI_EXAMPLE = (
    "POS,NO,DRIVER,TEAM,Q1,Q2,Q3\n"
    "1,12,Antonelli,Mercedes,1:18.234,1:17.812,1:17.345\n"
    "2,63,Russell,Mercedes,1:18.301,1:17.890,1:17.401\n"
    "3,44,Hamilton,Ferrari,1:18.412,1:18.001,1:17.502"
)
_SPRINT_RACE_EXAMPLE = (
    "position,car_number,driver,team,laps,time_or_retired,points\n"
    "1,63,Russell,Mercedes,23,28:50.951,8\n"
    "2,1,Norris,McLaren,23,+1.272s,7\n"
    "3,12,Antonelli,Mercedes,23,+1.843s,6"
)
_SPRINT_QUALI_EXAMPLE = (
    "position,car_number,driver,team,SQ1,SQ2,SQ3\n"
    "1,63,Russell,Mercedes,1:14.772,1:13.026,1:12.965\n"
    "2,12,Antonelli,Mercedes,1:14.010,1:13.551,1:13.033\n"
    "3,1,Norris,McLaren,1:14.265,1:13.957,1:13.280"
)

tabs_ingest = st.tabs(["Race", "Qualifying", "Sprint race", "Sprint qualifying"])
with tabs_ingest[0]:
    text = _csv_input("race results", "score_race_res", _RACE_EXAMPLE)
    if st.button("Save race results for this round", key="score_save_race"):
        res = ingest_race_results(text, PROJECT_ROOT, int(round_number), cfg=get_working_config())
        if res.ok:
            st.success(f"Saved {res.rows} drivers' race results for R{int(round_number)} -> {res.saved_path}")
            for w in res.warnings:
                st.warning(w)
        else:
            for e in res.errors:
                st.error(e)
with tabs_ingest[1]:
    text = _csv_input("qualifying results", "score_quali_res", _QUALI_EXAMPLE)
    if st.button("Save qualifying results for this round", key="score_save_quali"):
        res = ingest_qualifying_results(text, PROJECT_ROOT, int(round_number), cfg=get_working_config())
        if res.ok:
            st.success(f"Saved {res.rows} drivers' qualifying results for R{int(round_number)} -> {res.saved_path}")
            for w in res.warnings:
                st.warning(w)
        else:
            for e in res.errors:
                st.error(e)
with tabs_ingest[2]:
    text = _csv_input("sprint race results", "score_sprint_res", _SPRINT_RACE_EXAMPLE)
    if st.button("Save sprint race results for this round", key="score_save_sprint"):
        res = ingest_sprint_results(text, PROJECT_ROOT, int(round_number), cfg=get_working_config())
        if res.ok:
            st.success(f"Saved {res.rows} drivers' sprint race results for R{int(round_number)} -> {res.saved_path}")
            for w in res.warnings:
                st.warning(w)
        else:
            for e in res.errors:
                st.error(e)
with tabs_ingest[3]:
    text = _csv_input("sprint qualifying results", "score_sprint_quali_res", _SPRINT_QUALI_EXAMPLE)
    if st.button("Save sprint qualifying results for this round", key="score_save_sprint_quali"):
        res = ingest_sprint_qualifying_results(text, PROJECT_ROOT, int(round_number), cfg=get_working_config())
        if res.ok:
            st.success(f"Saved {res.rows} drivers' sprint qualifying for R{int(round_number)} -> {res.saved_path}")
            for w in res.warnings:
                st.warning(w)
        else:
            for e in res.errors:
                st.error(e)


# ---------------------------------------------------------------------------
# Existing entries for this round
# ---------------------------------------------------------------------------
hist_row = hist[hist["round"].astype(int) == int(round_number)] if not hist.empty else pd.DataFrame()
existing_model_pts = None
if not hist_row.empty:
    val = hist_row.iloc[0].get("actual_points", "")
    try:
        existing_model_pts = float(val) if str(val).strip() not in {"", "nan"} else None
    except (TypeError, ValueError):
        existing_model_pts = None

comp_round = comp_df[comp_df["round"].astype(int) == int(round_number)] if not comp_df.empty else pd.DataFrame()
existing_human = comp_round[comp_round["team_key"] == "human"]["points"].iloc[0] if not comp_round.empty and (comp_round["team_key"] == "human").any() else None
existing_claude = comp_round[comp_round["team_key"] == "claude_chat"]["points"].iloc[0] if not comp_round.empty and (comp_round["team_key"] == "claude_chat").any() else None


# ---------------------------------------------------------------------------
# Score entry form
# ---------------------------------------------------------------------------
st.header("2. Enter scores")
st.caption(
    "Enter the **official total** the F1 Fantasy site shows for each team. "
    "Optionally, paste the per-driver breakdown to capture a richer record for the visitor view."
)


def _team_score_block(
    team_key: str,
    label: str,
    placeholder_caption: str,
    existing_total: float | None,
    breakdown_placeholder: str,
) -> tuple[float, list, list[str]]:
    """Render one team's score input + optional breakdown paste. Returns (total, rows, warnings)."""
    st.markdown(f"**{label}**")
    st.caption(placeholder_caption)
    breakdown_text = st.text_area(
        "Paste per-driver breakdown (optional)",
        key=f"breakdown_{team_key}",
        height=170,
        placeholder=breakdown_placeholder,
    )
    rows, parsed_total, parse_warnings = parse_score_breakdown(breakdown_text, cfg)
    if rows:
        st.caption(f"Parsed sum from breakdown: **{parsed_total:.1f}** ({len(rows)} entries)")
    default_total = parsed_total if rows else (
        existing_total if existing_total is not None else 0.0
    )
    total = st.number_input(
        f"{label} — total points",
        min_value=-200.0, max_value=2000.0, value=float(default_total),
        step=0.5, key=f"score_{team_key}",
        help="Defaults to the parsed sum if you pasted a breakdown; otherwise enter manually.",
    )
    return total, rows, parse_warnings


_HUMAN_PLACEHOLDER = (
    "Russell: 54\n"
    "Gasly: 14\n"
    "Lawson: 10\n"
    "Sainz: 4\n"
    "Bearman: -14\n"
    "Ferrari: 75\n"
    "Racing Bulls: 18"
)
_CLAUDE_PLACEHOLDER = _HUMAN_PLACEHOLDER  # same format
_MODEL_PLACEHOLDER = _HUMAN_PLACEHOLDER

c1, c2, c3 = st.columns(3)
with c1:
    human_pts, human_breakdown, human_warns = _team_score_block(
        "human", THREE_TEAM_LABELS["human"],
        "Your scores from the official Fantasy F1 site.",
        existing_human, _HUMAN_PLACEHOLDER,
    )
with c2:
    claude_pts, claude_breakdown, claude_warns = _team_score_block(
        "claude_chat", THREE_TEAM_LABELS["claude_chat"],
        "Pure-AI Claude chat team's scores.",
        existing_claude, _CLAUDE_PLACEHOLDER,
    )
with c3:
    model_pts, model_breakdown, model_warns = _team_score_block(
        "model", THREE_TEAM_LABELS["model"],
        "From the official site — what the model's lineup actually scored.",
        existing_model_pts, _MODEL_PLACEHOLDER,
    )

for w in human_warns + claude_warns + model_warns:
    st.warning(w)

st.write("")

# ---------------------------------------------------------------------------
# Optional metadata edits (chips + model DRS)
# ---------------------------------------------------------------------------
existing_drs = ""
if not hist_row.empty:
    existing_drs = str(hist_row.iloc[0].get("drs_boost", "") or "").upper()

all_chip_options = [
    "autopilot",
    "extra_drs_boost",
    "no_negative",
    "wildcard",
    "limitless",
    "final_fix",
]

chips_hist = load_chip_usage(PROJECT_ROOT)
chips_round = chips_hist[chips_hist["round"].astype(int) == int(round_number)] if not chips_hist.empty else pd.DataFrame()


def _chip_defaults(team_key: str) -> tuple[str, str]:
    if chips_round.empty:
        return "none", ""
    row = chips_round[chips_round["team_key"] == team_key]
    if row.empty:
        return "none", ""
    chip_val = str(row.iloc[0].get("chip", "") or "").strip()
    details_val = str(row.iloc[0].get("details", "") or "")
    return (chip_val if chip_val else "none"), details_val


human_chip_default, human_chip_details_default = _chip_defaults("human")
claude_chip_default, claude_chip_details_default = _chip_defaults("claude_chat")
model_chip_default, model_chip_details_default = _chip_defaults("model")


def _drs_default(team_key: str) -> str:
    if chips_round.empty:
        return ""
    row = chips_round[chips_round["team_key"] == team_key]
    if row.empty:
        return ""
    return str(row.iloc[0].get("drs_boost", "") or "").upper().strip()


human_drs_default = _drs_default("human")
claude_drs_default = _drs_default("claude_chat")
model_drs_default = _drs_default("model")
if model_drs_default:
    existing_drs = model_drs_default

st.header("3. Chips + model DRS metadata (optional)")
st.caption(
    "Record chip usage + 2× DRS driver for each team. Useful for backfilling old rounds."
)
chip1, chip2, chip3 = st.columns(3)
with chip1:
    human_chip_options = ["none"] + all_chip_options
    human_chip_idx = human_chip_options.index(human_chip_default) if human_chip_default in human_chip_options else 0
    human_chip_used = st.selectbox("Team 1 chip", options=human_chip_options, index=human_chip_idx)
    human_chip_details = st.text_input(
        "Team 1 chip details",
        value=human_chip_details_default,
        placeholder="e.g. 3× on ANT, 2× on RUS",
        disabled=(human_chip_used == "none"),
    )
    human_used_drs = st.checkbox("Team 1 used 2× DRS", value=bool(human_drs_default), key="human_used_drs")
    _driver_opts = [""] + sorted((cfg.get("prices", {}).get("drivers", {}) or {}).keys())
    _human_drs_idx = _driver_opts.index(human_drs_default) if human_drs_default in _driver_opts else 0
    human_drs_boost = st.selectbox(
        "Team 1 DRS driver",
        options=_driver_opts,
        index=_human_drs_idx,
        format_func=lambda d: "— not set —" if d == "" else d,
        disabled=(not human_used_drs),
        key="human_drs_driver",
    )
with chip2:
    claude_chip_options = ["none"] + all_chip_options
    claude_chip_idx = claude_chip_options.index(claude_chip_default) if claude_chip_default in claude_chip_options else 0
    claude_chip_used = st.selectbox("Team 2 chip", options=claude_chip_options, index=claude_chip_idx)
    claude_chip_details = st.text_input(
        "Team 2 chip details",
        value=claude_chip_details_default,
        placeholder="e.g. played no_negative for wet race",
        disabled=(claude_chip_used == "none"),
    )
    claude_used_drs = st.checkbox("Team 2 used 2× DRS", value=bool(claude_drs_default), key="claude_used_drs")
    _claude_drs_idx = _driver_opts.index(claude_drs_default) if claude_drs_default in _driver_opts else 0
    claude_drs_boost = st.selectbox(
        "Team 2 DRS driver",
        options=_driver_opts,
        index=_claude_drs_idx,
        format_func=lambda d: "— not set —" if d == "" else d,
        disabled=(not claude_used_drs),
        key="claude_drs_driver",
    )
with chip3:
    model_chip_options = ["none"] + all_chip_options
    model_chip_idx = model_chip_options.index(model_chip_default) if model_chip_default in model_chip_options else 0
    scored_chip_used = st.selectbox("Team 3 chip", options=model_chip_options, index=model_chip_idx)
    scored_chip_details = st.text_input(
        "Team 3 chip details",
        value=model_chip_details_default,
        placeholder="e.g. 3× on RUS, 2× on HAM",
        disabled=(scored_chip_used == "none"),
    )

st.markdown("##### Team 3 (model) 2× DRS")
with st.container():
    drs_options = [""] + sorted((cfg.get("prices", {}).get("drivers", {}) or {}).keys())
    default_drs_index = drs_options.index(existing_drs) if existing_drs in drs_options else 0
    scored_drs_boost = st.selectbox(
        "2× DRS driver used by model team",
        options=drs_options,
        index=default_drs_index,
        format_func=lambda d: "— not set —" if d == "" else d,
    )

if st.button("Save scores for this round", type="primary", key="save_scores"):
    paths_changed: list[str] = []

    # 1. Ensure model history row exists for this round (for History/transfer log views)
    if hist_row.empty:
        inferred_drivers = [str(r.asset).upper() for r in model_breakdown if str(r.kind).lower() == "driver"]
        inferred_ctors = [str(r.asset).lower() for r in model_breakdown if str(r.kind).lower() == "constructor"]
        if not inferred_drivers:
            inferred_drivers = list(cfg.get("current_team", {}).get("drivers", []) or [])
        if not inferred_ctors:
            inferred_ctors = list(cfg.get("current_team", {}).get("constructors", []) or [])
        lockin_p = append_lockin(
            project_root=PROJECT_ROOT,
            round_number=int(round_number),
            drivers=inferred_drivers,
            constructors=inferred_ctors,
            drs_boost=(scored_drs_boost or cfg.get("current_team", {}).get("drs_boost")),
            chips_used=([scored_chip_used] if scored_chip_used != "none" else []),
            budget_after=float(cfg.get("current_team", {}).get("budget", 0.0) or 0.0),
            free_transfers_after=int(cfg.get("current_team", {}).get("free_transfers", 2) or 2),
            banked_transfers_after=int(cfg.get("current_team", {}).get("banked_transfers", 0) or 0),
            notes="Auto-created from Score Round (missing lock-in row).",
            chip_details=(scored_chip_details if scored_chip_used != "none" else ""),
        )
        paths_changed.append(str(lockin_p))

    # 2. Update model team's actual_points in history.csv
    if not hist_row.empty:
        p = update_actual_points(PROJECT_ROOT, int(round_number), float(model_pts))
        if p:
            paths_changed.append(str(p))
        p_meta = update_lockin_metadata(
            PROJECT_ROOT,
            int(round_number),
            drs_boost=(scored_drs_boost or None),
            chips_used=([scored_chip_used] if scored_chip_used != "none" else []),
            chip_details=(scored_chip_details if scored_chip_used != "none" else ""),
        )
        if p_meta:
            paths_changed.append(str(p_meta))
    else:
        p = update_actual_points(PROJECT_ROOT, int(round_number), float(model_pts))
        if p:
            paths_changed.append(str(p))
        p_meta = update_lockin_metadata(
            PROJECT_ROOT,
            int(round_number),
            drs_boost=(scored_drs_boost or None),
            chips_used=([scored_chip_used] if scored_chip_used != "none" else []),
            chip_details=(scored_chip_details if scored_chip_used != "none" else ""),
        )
        if p_meta:
            paths_changed.append(str(p_meta))

    # 3. Append/replace competitor rows
    p_human = append_competitor_score(PROJECT_ROOT, int(round_number), "human", float(human_pts))
    p_claude = append_competitor_score(PROJECT_ROOT, int(round_number), "claude_chat", float(claude_pts))
    if hist_row.empty:
        # No lock-in for this round — also store the model team's score in competitors.csv
        # so it shows up in the leaderboard / charts despite the missing history row.
        append_competitor_score(PROJECT_ROOT, int(round_number), "model", float(model_pts))

    # 4. Save chip usage rows (all teams)
    chip_h = append_chip_usage(
        PROJECT_ROOT,
        int(round_number),
        "human",
        human_chip_used,
        human_chip_details,
        drs_boost=(human_drs_boost if human_used_drs else ""),
    )
    chip_c = append_chip_usage(
        PROJECT_ROOT,
        int(round_number),
        "claude_chat",
        claude_chip_used,
        claude_chip_details,
        drs_boost=(claude_drs_boost if claude_used_drs else ""),
    )
    chip_m = append_chip_usage(
        PROJECT_ROOT,
        int(round_number),
        "model",
        scored_chip_used,
        scored_chip_details,
        drs_boost=(scored_drs_boost or ""),
    )
    paths_changed += [str(chip_h), str(chip_c), str(chip_m)]

    # 5. Save breakdowns (if any team's breakdown was pasted)
    for team_key, rows in (
        ("human", human_breakdown),
        ("claude_chat", claude_breakdown),
        ("model", model_breakdown),
    ):
        if rows:
            bp = append_breakdown(
                PROJECT_ROOT, int(round_number), team_key,
                [{"asset": r.asset, "name": r.name, "kind": r.kind, "points": r.points} for r in rows],
            )
            paths_changed.append(str(bp))
    paths_changed += [str(p_human), str(p_claude)]

    st.success(f"Saved scores for R{int(round_number)}: human {human_pts:.1f} · claude {claude_pts:.1f} · model {model_pts:.1f}")
    for pth in paths_changed:
        st.caption(f"Updated {pth}")

    # 3. Auto-PR if creds configured (commits both history.csv + competitors.csv)
    gh = github_settings_from_secrets()
    if gh.get("token") and gh["token"] != "ghp_xxx":
        files_to_pr: dict[str, str] = {}
        h_path = history_path(PROJECT_ROOT)
        if h_path.exists():
            files_to_pr["data/fantasy/history.csv"] = h_path.read_text()
        c_path = competitors_path(PROJECT_ROOT)
        if c_path.exists():
            files_to_pr["data/fantasy/competitors.csv"] = c_path.read_text()
        b_path = breakdowns_path(PROJECT_ROOT)
        if b_path.exists():
            files_to_pr["data/fantasy/breakdowns.csv"] = b_path.read_text()
        chip_path = chips_path(PROJECT_ROOT)
        if chip_path.exists():
            files_to_pr["data/fantasy/chips.csv"] = chip_path.read_text()
        with st.spinner("Opening PR with score updates…"):
            pr = propose_files_pr(
                files=files_to_pr,
                title=f"Score R{int(round_number)} (human {human_pts:.0f} · claude {claude_pts:.0f} · model {model_pts:.0f})",
                body="Auto-PR from Score Round page.",
                branch_prefix="score-round",
                settings=gh,
            )
        if pr.ok:
            st.success(f"PR opened: {pr.pr_url}")
        else:
            st.warning(f"PR write-back failed: {pr.message}")
    else:
        st.caption("GitHub creds not configured — files saved locally. Add `GITHUB_TOKEN` to enable auto-PR.")


# ---------------------------------------------------------------------------
# All scored rounds — quick reference table
# ---------------------------------------------------------------------------
st.markdown("---")
st.header("Already-scored rounds")
if comp_df.empty and (hist.empty or "actual_points" not in hist.columns):
    st.caption("No scores recorded yet.")
else:
    summary = pd.DataFrame()
    if not hist.empty and "actual_points" in hist.columns:
        m = hist[["round", "actual_points"]].copy()
        m = m[pd.to_numeric(m["actual_points"], errors="coerce").notna()]
        m["team"] = THREE_TEAM_LABELS["model"]
        m["points"] = pd.to_numeric(m["actual_points"], errors="coerce")
        summary = pd.concat([summary, m[["round", "team", "points"]]], ignore_index=True)
    if not comp_df.empty:
        c = comp_df[["round", "team_name", "points"]].rename(columns={"team_name": "team"}).copy()
        summary = pd.concat([summary, c], ignore_index=True)

    cancelled_rounds = {r for r in calendar_rounds(calendar) if is_cancelled(calendar, r)}
    if cancelled_rounds and not summary.empty:
        summary = summary[~summary["round"].astype(int).isin(cancelled_rounds)]

    if summary.empty:
        st.caption("No scores recorded yet.")
    else:
        summary["Race"] = summary["round"].astype(int).apply(lambda r: format_round_label(calendar, r, short=True))
        pivot = summary.pivot_table(index="Race", columns="team", values="points", aggfunc="last")
        st.dataframe(pivot, use_container_width=True)

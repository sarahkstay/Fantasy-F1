from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.components import F1_RED, inject_theme, per_round_chart, team_color
from frontend.state import get_working_config, is_owner
from src.ui_services import (
    THREE_TEAM_LABELS,
    calendar_rounds,
    cumulative_points_by_team,
    current_leaderboard,
    is_cancelled,
    latest_round_in_history,
)


inject_theme()


# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------
st.title("Fantasy F1 2026")
st.markdown("##### Three teams. One season. Who wins — model, human, or AI?")
st.write(
    "An experiment running across the full 2026 F1 season. Three Fantasy F1 teams, "
    "each picking lineups using a different decision-making approach, all tracked "
    "round by round."
)


# ---------------------------------------------------------------------------
# Three-team leaderboard
# ---------------------------------------------------------------------------
st.markdown("---")
st.header("Season standings")

leaderboard = current_leaderboard(PROJECT_ROOT)
latest_round = latest_round_in_history(PROJECT_ROOT) or 0

if leaderboard.empty:
    st.info(
        "Season hasn't started yet — no scored rounds in the leaderboard. "
        "The standings will populate after the first race is locked in and scored."
    )
    placeholder = [
        {"team_key": "human", "team_name": THREE_TEAM_LABELS["human"], "cumulative_points": 0, "rank": "—"},
        {"team_key": "claude_chat", "team_name": THREE_TEAM_LABELS["claude_chat"], "cumulative_points": 0, "rank": "—"},
        {"team_key": "model", "team_name": THREE_TEAM_LABELS["model"], "cumulative_points": 0, "rank": "—"},
    ]
    leaderboard = pd.DataFrame(placeholder)


def _team_card(rank: Any, team_key: str, team_name: str, points: float) -> None:
    if team_key == "model":
        accent = F1_RED
    elif team_key == "human":
        accent = "#00D2BE"
    elif team_key == "claude_chat":
        accent = "#FF8000"
    else:
        accent = "#888"

    st.markdown(
        f"""
        <div style="
            border-left: 4px solid {accent};
            background: linear-gradient(135deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01));
            padding: 1rem 1.2rem;
            border-radius: 6px;
            min-height: 110px;
        ">
            <div style="font-size:0.7rem;letter-spacing:0.12em;opacity:0.6;text-transform:uppercase;">
                {team_name}
            </div>
            <div style="display:flex;align-items:baseline;gap:0.6rem;margin-top:0.4rem;">
                <span style="font-size:2.2rem;font-weight:800;color:{accent};">P{rank}</span>
                <span style="font-size:1.4rem;font-weight:700;">{points:.0f} pts</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


cols = st.columns(3)
for i, row in leaderboard.iterrows():
    with cols[i % 3]:
        _team_card(
            rank=row["rank"],
            team_key=row["team_key"],
            team_name=row["team_name"],
            points=float(row["cumulative_points"]),
        )

if latest_round:
    st.caption(f"Standings through Round {latest_round}.")


# ---------------------------------------------------------------------------
# Per-round performance chart
# ---------------------------------------------------------------------------
st.markdown("---")
st.header("Performance over time")

_cfg_for_calendar = get_working_config()
_calendar = _cfg_for_calendar.get("season", {}).get("calendar", {})
_cancelled = {r for r in calendar_rounds(_calendar) if is_cancelled(_calendar, r)}
_sprint_rounds = set(_cfg_for_calendar.get("season", {}).get("sprint_rounds", []) or [])

cum = cumulative_points_by_team(PROJECT_ROOT)
if not cum.empty and _cancelled:
    cum = cum[~cum["round"].astype(int).isin(_cancelled)].copy()
if cum.empty:
    st.info("No scored rounds yet — this chart fills in as the season progresses.")
else:
    st.altair_chart(per_round_chart(cum, _calendar, sprint_rounds=_sprint_rounds), use_container_width=True)
    st.caption("Side-by-side bars per race. ★ = sprint weekend (more scoring sessions -> higher totals).")


# ---------------------------------------------------------------------------
# Current model team snapshot
# ---------------------------------------------------------------------------
cfg = get_working_config()
team = cfg.get("current_team", {})
drivers = team.get("drivers", []) or []
constructors = team.get("constructors", []) or []
drs = team.get("drs_boost", "")
budget = team.get("budget", 0.0)
free_t = team.get("free_transfers", 0)
banked_t = team.get("banked_transfers", 0)
prices_drivers = cfg.get("prices", {}).get("drivers", {})
prices_ctors = cfg.get("prices", {}).get("constructors", {})

st.markdown("---")
st.header("Current model team")
st.caption("The lineup the data science model is fielding right now.")

mcol1, mcol2, mcol3 = st.columns(3)
with mcol1:
    st.metric("Bank remaining", f"£{float(budget):.1f}M")
with mcol2:
    st.metric("Free transfers", f"{int(free_t)} (+{int(banked_t)} banked)")
with mcol3:
    st.metric("DRS Boost", drs or "—")


def _driver_pill(code: str) -> str:
    meta = prices_drivers.get(code, {})
    color = team_color(meta.get("team", ""))
    name = meta.get("name", code)
    price = meta.get("price", "?")
    return (
        f'<div style="display:inline-block;background:rgba(255,255,255,0.04);'
        f'border-left:3px solid {color};border-radius:4px;padding:0.5rem 0.8rem;'
        f'margin:0.2rem 0.4rem 0.2rem 0;min-width:160px;">'
        f'<div style="font-size:0.7rem;opacity:0.6;text-transform:uppercase;letter-spacing:0.08em;">{code}</div>'
        f'<div style="font-weight:700;">{name}</div>'
        f'<div style="font-size:0.85rem;opacity:0.7;">£{price}M</div>'
        f"</div>"
    )


def _constructor_pill(cid: str) -> str:
    meta = prices_ctors.get(cid, {})
    color = team_color(cid)
    name = meta.get("name", cid)
    price = meta.get("price", "?")
    return (
        f'<div style="display:inline-block;background:rgba(255,255,255,0.04);'
        f'border-left:3px solid {color};border-radius:4px;padding:0.5rem 0.8rem;'
        f'margin:0.2rem 0.4rem 0.2rem 0;min-width:160px;">'
        f'<div style="font-size:0.7rem;opacity:0.6;text-transform:uppercase;letter-spacing:0.08em;">CONSTRUCTOR</div>'
        f'<div style="font-weight:700;">{name}</div>'
        f'<div style="font-size:0.85rem;opacity:0.7;">£{price}M</div>'
        f"</div>"
    )


st.markdown("**Drivers**")
st.markdown("".join(_driver_pill(d) for d in drivers), unsafe_allow_html=True)

st.markdown("**Constructors**")
st.markdown("".join(_constructor_pill(c) for c in constructors), unsafe_allow_html=True)


if is_owner():
    st.markdown("---")
    st.caption("**Owner shortcut:** the weekly wizard is in the sidebar under **This Week**.")

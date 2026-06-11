"""Altair charts for the visitor pages — team brand colors, race-name tick labels,
cancelled-round indicators, and rich hover tooltips.
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd

from frontend.components.theme import F1_RED, team_color
from src.ui_services import calendar_rounds, format_round_label, is_cancelled


# Team brand palette for the 3 experiment teams. Matched to the landing-page cards
# so colors stay consistent across the app.
TEAM_VIZ_COLORS: dict[str, str] = {
    "Pure human judgement": "#00D2BE",
    "Pure-AI Claude chat": "#FF8000",
    "Vibe-coded data science model": F1_RED,
}


def _add_race_label(df: pd.DataFrame, calendar: dict[Any, Any]) -> pd.DataFrame:
    df = df.copy()
    df["race_label"] = df["round"].astype(int).apply(
        lambda r: format_round_label(calendar, r, short=True)
    )
    return df


def _color_scale() -> alt.Scale:
    return alt.Scale(
        domain=list(TEAM_VIZ_COLORS.keys()),
        range=list(TEAM_VIZ_COLORS.values()),
    )


def _x_axis_labels_js(calendar: dict[Any, Any], sprint_rounds: set[int] | None = None) -> str:
    """Build a Vega `labelExpr` mapping round numbers to short race labels.

    Cancelled rounds are flagged with ✗. Sprint rounds get a ★.
    """
    sprint_rounds = sprint_rounds or set()
    pairs: list[str] = []
    for r in calendar_rounds(calendar, include_cancelled=True):
        event = calendar.get(r) or calendar.get(int(r)) or {}
        country = event.get("country", "")
        cancelled = is_cancelled(calendar, r)
        marker = ""
        if cancelled:
            marker = " ✗"
        elif int(r) in sprint_rounds:
            marker = " ★"
        label = f"R{r}"
        if country:
            label += f" {country}"
        label += marker
        # Escape any embedded quotes (none expected here, but defensive)
        label = label.replace('"', '\\"')
        pairs.append(f'{int(r)}: "{label}"')
    obj = "{" + ", ".join(pairs) + "}"
    return f"{obj}[datum.value] || ('R' + datum.value)"


def _cancelled_overlays(
    calendar: dict[Any, Any], y_min: float | None = None, y_max: float | None = None
) -> tuple[alt.Chart, alt.Chart] | None:
    """Vertical dashed rules + 'cancelled' labels at cancelled rounds. Returns None if none."""
    cancelled = [r for r in calendar_rounds(calendar) if is_cancelled(calendar, r)]
    if not cancelled:
        return None
    df_rules = pd.DataFrame({"round": cancelled})
    rule = (
        alt.Chart(df_rules)
        .mark_rule(color="#888", strokeDash=[3, 3], opacity=0.7)
        .encode(x="round:Q")
    )
    label_df = pd.DataFrame({
        "round": cancelled,
        "label": ["cancelled"] * len(cancelled),
        "y": [y_max if y_max is not None else 0] * len(cancelled),
    })
    text = (
        alt.Chart(label_df)
        .mark_text(color="#888", fontSize=10, angle=270, dy=-32, align="left")
        .encode(x="round:Q", y="y:Q", text="label:N")
    )
    return rule, text


def cumulative_chart(cum_df: pd.DataFrame, calendar: dict[Any, Any]) -> alt.Chart:
    df = _add_race_label(cum_df, calendar)
    label_expr = _x_axis_labels_js(calendar)
    tooltips = [
        alt.Tooltip("race_label:N", title="Race"),
        alt.Tooltip("team_name:N", title="Team"),
        alt.Tooltip("cumulative_points:Q", title="Cumulative", format=".0f"),
        alt.Tooltip("round_points:Q", title="This round", format=".0f"),
    ]
    if "chip" in df.columns:
        tooltips.append(alt.Tooltip("chip:N", title="Chip used"))
    if "chip_details" in df.columns:
        tooltips.append(alt.Tooltip("chip_details:N", title="Chip details"))

    lines = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(size=80, filled=True), strokeWidth=3)
        .encode(
            x=alt.X(
                "round:Q", title="Round",
                axis=alt.Axis(
                    labelExpr=label_expr, labelAngle=-30, tickMinStep=1,
                    values=calendar_rounds(calendar, include_cancelled=True),
                ),
            ),
            y=alt.Y("cumulative_points:Q", title="Cumulative points"),
            color=alt.Color(
                "team_name:N", scale=_color_scale(),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=tooltips,
        )
    )
    if "chip_used" in df.columns:
        chip_pts = df[df["chip_used"]].copy()
        if not chip_pts.empty:
            star = (
                alt.Chart(chip_pts)
                .mark_text(text="★", dy=-12, fontSize=15, color="#FFD166")
                .encode(x="round:Q", y="cumulative_points:Q")
            )
            lines = lines + star
    overlays = _cancelled_overlays(calendar, y_max=float(df["cumulative_points"].max()))
    chart = lines
    if overlays:
        chart = chart + overlays[0] + overlays[1]
    return chart.properties(height=380)


def per_round_chart(
    cum_df: pd.DataFrame,
    calendar: dict[Any, Any],
    sprint_rounds: set[int] | None = None,
) -> alt.Chart:
    df = _add_race_label(cum_df, calendar)
    label_expr = _x_axis_labels_js(calendar, sprint_rounds=sprint_rounds or set())
    tooltips = [
        alt.Tooltip("race_label:N", title="Race"),
        alt.Tooltip("team_name:N", title="Team"),
        alt.Tooltip("round_points:Q", title="Points", format=".0f"),
    ]
    if "chip" in df.columns:
        tooltips.append(alt.Tooltip("chip:N", title="Chip used"))
    if "chip_details" in df.columns:
        tooltips.append(alt.Tooltip("chip_details:N", title="Chip details"))

    bars = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(
                "round:O", title="Round",
                sort=alt.EncodingSortField("round"),
                axis=alt.Axis(labelExpr=label_expr, labelAngle=-30),
            ),
            xOffset=alt.XOffset("team_name:N"),
            y=alt.Y("round_points:Q", title="Points scored"),
            color=alt.Color(
                "team_name:N", scale=_color_scale(),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=tooltips,
        )
        .properties(height=380)
    )
    if "chip_used" in df.columns:
        chip_pts = df[df["chip_used"]].copy()
        if not chip_pts.empty:
            stars = (
                alt.Chart(chip_pts)
                .mark_text(text="★", dy=-10, fontSize=14, color="#FFD166")
                .encode(
                    x=alt.X("round:O", sort=alt.EncodingSortField("round")),
                    xOffset=alt.XOffset("team_name:N"),
                    y=alt.Y("round_points:Q"),
                )
            )
            return bars + stars
    return bars


def delta_vs_human_chart(cum_df: pd.DataFrame, calendar: dict[Any, Any]) -> alt.Chart | None:
    """Round-by-round points gap to the human team. Returns None if human has no data."""
    human = cum_df[cum_df["team_key"] == "human"].set_index("round")["round_points"]
    if human.empty:
        return None

    df = cum_df[cum_df["team_key"] != "human"].copy()
    if df.empty:
        return None

    df["delta_vs_human"] = df.apply(lambda r: float(r["round_points"]) - float(human.get(int(r["round"]), 0)), axis=1)
    df = _add_race_label(df, calendar)
    label_expr = _x_axis_labels_js(calendar)
    tooltips = [
        alt.Tooltip("race_label:N", title="Race"),
        alt.Tooltip("team_name:N", title="Team"),
        alt.Tooltip("delta_vs_human:Q", title="Vs human (this round)", format="+.0f"),
        alt.Tooltip("round_points:Q", title="Team round points", format=".0f"),
    ]
    if "chip" in df.columns:
        tooltips.append(alt.Tooltip("chip:N", title="Chip used"))
    if "chip_details" in df.columns:
        tooltips.append(alt.Tooltip("chip_details:N", title="Chip details"))

    rule_zero = (
        alt.Chart(pd.DataFrame({"zero": [0]}))
        .mark_rule(color="#888", strokeDash=[5, 5])
        .encode(y="zero:Q")
    )
    bars = (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X(
                "round:O", title="Round",
                sort=alt.EncodingSortField("round"),
                axis=alt.Axis(labelExpr=label_expr, labelAngle=-30),
            ),
            xOffset=alt.XOffset("team_name:N"),
            y=alt.Y("delta_vs_human:Q", title="Points vs human (this round)"),
            color=alt.Color(
                "team_name:N", scale=_color_scale(),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=tooltips,
        )
    )
    chart = rule_zero + bars
    if "chip_used" in df.columns:
        chip_pts = df[df["chip_used"]].copy()
        if not chip_pts.empty:
            stars = (
                alt.Chart(chip_pts)
                .mark_text(text="★", dy=-10, fontSize=14, color="#FFD166")
                .encode(
                    x=alt.X("round:O", sort=alt.EncodingSortField("round")),
                    xOffset=alt.XOffset("team_name:N"),
                    y=alt.Y("delta_vs_human:Q"),
                )
            )
            chart = chart + stars
    return chart.properties(height=380)


_GANTT_EMPTY_COLOR = "#222230"      # not on team this round
_GANTT_CANCELLED_COLOR = "#2a1414"  # round was cancelled


def driver_tenure_gantt(
    ownership_df: pd.DataFrame,
    calendar: dict[Any, Any],
    drivers_cfg: dict[str, Any] | None = None,
) -> alt.Chart | None:
    """GitHub-contribution-style cell grid: drivers × rounds.

    Every round in the calendar is rendered. Owned cells are filled with the
    driver's team color; rounds where the driver wasn't on the team show as
    dim grey; cancelled rounds show as a dim red so the gap is explained.
    """
    if ownership_df.empty:
        return None

    own = ownership_df.copy()
    own["round"] = own["round"].astype(int)

    all_rounds = calendar_rounds(calendar, include_cancelled=True)
    drivers_owned = sorted(own["driver"].astype(str).unique())
    cancelled = {r for r in all_rounds if is_cancelled(calendar, r)}
    owned_set = set(zip(own["driver"].astype(str), own["round"].astype(int)))

    rows: list[dict[str, Any]] = []
    for d in drivers_owned:
        team_id = (drivers_cfg or {}).get(d, {}).get("team", "") if drivers_cfg else ""
        for r in all_rounds:
            is_owned = (d, r) in owned_set
            is_cancel = r in cancelled
            if is_cancel:
                color = _GANTT_CANCELLED_COLOR
                status = "cancelled"
            elif is_owned:
                color = team_color(team_id) if team_id else "#888"
                status = "on team"
            else:
                color = _GANTT_EMPTY_COLOR
                status = "—"
            rows.append({
                "driver": d,
                "round": r,
                "race_label": format_round_label(calendar, r, short=True),
                "team_id": team_id if is_owned else "",
                "color": color,
                "status": status,
            })
    df = pd.DataFrame(rows)

    # Sort drivers: most-tenured first (longest "spine" at top)
    counts = own.groupby("driver").size().rename("count").reset_index()
    driver_order = (
        counts.sort_values(["count", "driver"], ascending=[False, True])["driver"].tolist()
    )

    label_expr = _x_axis_labels_js(calendar)

    return (
        alt.Chart(df)
        .mark_rect(stroke="#15151E", strokeWidth=2, cornerRadius=2)
        .encode(
            x=alt.X(
                "round:O", title=None,
                sort=all_rounds,
                axis=alt.Axis(labelExpr=label_expr, labelAngle=-30, labelPadding=6),
            ),
            y=alt.Y("driver:N", title=None, sort=driver_order),
            color=alt.Color("color:N", scale=None, legend=None),
            tooltip=[
                alt.Tooltip("driver:N", title="Driver"),
                alt.Tooltip("race_label:N", title="Race"),
                alt.Tooltip("status:N", title="Status"),
                alt.Tooltip("team_id:N", title="Team"),
            ],
        )
        .properties(height=alt.Step(22), width=alt.Step(24))
    )


def prediction_vs_actual_chart(df: pd.DataFrame, round_number: int) -> alt.Chart:
    """Paired bars per driver: predicted (grey) vs actual (F1 red)."""
    long = pd.concat([
        df[["driver_code", "predicted"]].rename(columns={"predicted": "value"}).assign(metric="Predicted"),
        df[["driver_code", "actual"]].rename(columns={"actual": "value"}).assign(metric="Actual"),
    ], ignore_index=True)
    driver_order = df.sort_values("actual", ascending=False)["driver_code"].tolist()
    return (
        alt.Chart(long)
        .mark_bar()
        .encode(
            x=alt.X("driver_code:N", title="Driver", sort=driver_order, axis=alt.Axis(labelAngle=-30)),
            xOffset=alt.XOffset("metric:N"),
            y=alt.Y("value:Q", title="Fantasy points"),
            color=alt.Color(
                "metric:N",
                scale=alt.Scale(domain=["Predicted", "Actual"], range=["#888888", F1_RED]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("driver_code:N", title="Driver"),
                alt.Tooltip("metric:N"),
                alt.Tooltip("value:Q", title="Points", format=".1f"),
            ],
        )
        .properties(height=340, title=f"R{round_number} — predicted vs actual")
    )


def prediction_accuracy_chart(acc_df: pd.DataFrame, calendar: dict[Any, Any]) -> alt.Chart:
    """Line chart of MAE per round (lower = better)."""
    df = acc_df.copy()
    df["round"] = df["round"].astype(int)
    df["race_label"] = df["round"].apply(lambda r: format_round_label(calendar, r, short=True))
    label_expr = _x_axis_labels_js(calendar)
    return (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(size=120, filled=True), strokeWidth=3, color=F1_RED)
        .encode(
            x=alt.X(
                "round:Q", title="Round",
                axis=alt.Axis(
                    labelExpr=label_expr, labelAngle=-30, tickMinStep=1,
                    values=calendar_rounds(calendar, include_cancelled=True),
                ),
            ),
            y=alt.Y("mae:Q", title="Mean absolute error (pts / driver)"),
            tooltip=[
                alt.Tooltip("race_label:N", title="Race"),
                alt.Tooltip("mae:Q", title="MAE", format=".1f"),
                alt.Tooltip("n_drivers:Q", title="# drivers"),
            ],
        )
        .properties(height=300)
    )

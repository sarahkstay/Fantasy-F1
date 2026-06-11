from __future__ import annotations

import sys
from pathlib import Path

import datetime as dt
import os
import subprocess
from typing import Any

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
    set_working_config,
)
from src.ui_services import (
    append_lockin,
    c_to_f,
    calendar_rounds,
    compute_team_points_for_round,
    dump_config_yaml,
    format_round_label,
    generate_config_diff,
    history_path,
    ingest_constructor_prices,
    ingest_driver_prices,
    is_cancelled,
    load_config_file,
    next_active_round,
    parse_weather_description,
    propose_files_pr,
    recommend_round,
    recommend_transfers,
    save_price_snapshot,
    update_current_team,
    update_weather_override,
)


require_auth()

if not is_owner():
    inject_theme()
    st.title("This Week")
    st.warning("This page is for the team principal only. Switch to **Performance** in the sidebar to follow the season.")
    st.stop()

inject_theme()

st.title("This Week")
st.caption("Upload latest data → see recommendation → lock in.")


# ---------------------------------------------------------------------------
# 1. Race context
# ---------------------------------------------------------------------------
cfg = get_working_config()
season = cfg.get("season", {})
weather = cfg.get("weather_override", {})
team = cfg.get("current_team", {})
calendar = season.get("calendar", {})

st.header("1. Race context")

all_rounds = calendar_rounds(calendar, include_cancelled=True)
round_default_raw = int(weather.get("next_race_round", 1))
round_default = next_active_round(calendar, round_default_raw)

if not all_rounds:
    all_rounds = list(range(1, int(season.get("total_rounds", 24)) + 1))

try:
    default_index = all_rounds.index(round_default)
except ValueError:
    default_index = 0

round_number = st.selectbox(
    "Next round",
    options=all_rounds,
    index=default_index,
    format_func=lambda r: format_round_label(calendar, r),
    help="Pick the round you're preparing for. Cancelled rounds stay listed but are flagged.",
)
if is_cancelled(calendar, int(round_number)):
    st.warning(f"R{int(round_number)} is marked **cancelled** in config.yaml — recommendations may not be meaningful.")

st.markdown("##### Weather")
forecast_text = st.text_area(
    "Paste a forecast description (optional)",
    value="",
    placeholder="e.g. 22°C, partly cloudy with a 60% chance of light showers around 3pm",
    height=68,
    key="forecast_text",
)
if st.button("Parse forecast", key="parse_forecast"):
    parsed = parse_weather_description(forecast_text)
    if parsed.rain_probability is not None:
        st.session_state["wx_rain"] = parsed.rain_probability
    if parsed.temperature_c is not None:
        st.session_state["wx_temp_c"] = parsed.temperature_c
    bits = []
    if parsed.matched_phrase:
        bits.append(f"rain → **{int((parsed.rain_probability or 0)*100)}%** (matched: _{parsed.matched_phrase}_)")
    if parsed.matched_temperature_phrase:
        bits.append(f"temperature → **{parsed.temperature_c:.1f}°C** (matched: _{parsed.matched_temperature_phrase}_)")
    if bits:
        st.success("Parsed: " + " · ".join(bits))
    else:
        st.warning("Couldn't extract rain or temperature. Set them manually below.")

wa, wb, wc = st.columns([1, 1, 2])


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# Guard against stale/out-of-range widget state causing StreamlitValueBelowMinError
# on Cloud reruns after forecast parsing or app upgrades.
try:
    _seed_rain = float(st.session_state.get("wx_rain", weather.get("rain_probability", 0.0)))
except Exception:
    _seed_rain = float(weather.get("rain_probability", 0.0) or 0.0)
try:
    _seed_temp = float(st.session_state.get("wx_temp_c", weather.get("temperature_c", 22.0)))
except Exception:
    _seed_temp = float(weather.get("temperature_c", 22.0) or 22.0)

st.session_state["wx_rain"] = _clamp(_seed_rain, 0.0, 1.0)
st.session_state["wx_temp_c"] = _clamp(_seed_temp, -10.0, 55.0)

with wa:
    rain = st.slider(
        "Rain probability",
        min_value=0.0, max_value=1.0,
        value=float(st.session_state["wx_rain"]),
        step=0.05,
        key="wx_rain",
    )
with wb:
    temp_c = st.number_input(
        "Temperature (°C)",
        min_value=-10.0, max_value=55.0,
        value=float(st.session_state["wx_temp_c"]),
        step=0.5,
        key="wx_temp_c",
    )
    st.caption(f"= **{c_to_f(temp_c):.0f}°F** · {'cool tyres' if temp_c < 18 else 'warm tyres' if temp_c < 30 else 'hot tyres → faster deg'}")
with wc:
    notes = st.text_input("Notes (kept in history)", value=str(weather.get("notes", "")))


# ---------------------------------------------------------------------------
# 2. Latest data (CSV uploads)
# ---------------------------------------------------------------------------
st.header("2. Latest data")
st.caption("Update prices + transfer allowance for this week. Round scoring/session result uploads live on the Score Round page.")

tabs = st.tabs(["Prices (drivers + constructors)"])


def _csv_input(label: str, key: str, placeholder: str) -> str:
    """Return the CSV text from either a file upload or pasted area."""
    upload = st.file_uploader(f"Upload {label} CSV", type=["csv"], key=f"{key}_file")
    pasted = st.text_area(
        f"…or paste {label} CSV", key=f"{key}_paste", height=160, placeholder=placeholder,
    )
    if upload is not None:
        return upload.getvalue().decode("utf-8")
    return pasted


_PRICES_EXAMPLE = (
    "type,name,price_million_usd,pct_picked,season_pts\n"
    "Driver,George Russell,28.6,27.00%,153\n"
    "Driver,Max Verstappen,28.3,17.00%,129\n"
    "Driver,Lando Norris,26.4,9.00%,89\n"
    "Constructor,Mercedes,30.5,33.00%,407\n"
    "Constructor,Red Bull Racing,29.2,7.00%,143\n"
    "...\n"
    "(Single column 'name' for both; rows are split by 'type'. "
    "Extra columns are ignored.)"
)
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


# Derived from the single round selector in section 1: prices apply ahead
# of `round_number`.
prices_round = int(round_number)

st.caption(
    f"Prices apply ahead of **{format_round_label(calendar, prices_round, short=True)}**. "
    "Use the Score Round page to upload race/qualifying/sprint session results."
)


with tabs[0]:
    text = _csv_input("prices", "all_prices", _PRICES_EXAMPLE)
    if st.button("Apply prices", key="apply_prices"):
        cfg_now = get_working_config()
        drv_res = ingest_driver_prices(cfg_now, text)
        if not drv_res.ok:
            for e in drv_res.errors:
                st.error(f"Drivers: {e}")
        else:
            cfg_now = drv_res.updated_config
            ctor_res = ingest_constructor_prices(cfg_now, text)
            if not ctor_res.ok:
                for e in ctor_res.errors:
                    st.error(f"Constructors: {e}")
            else:
                set_working_config(ctor_res.updated_config)
                snap = save_price_snapshot(text, PROJECT_ROOT, prices_round, "combined")
                st.success(
                    f"Updated **{drv_res.rows} drivers** + **{ctor_res.rows} constructors** "
                    f"(prices apply ahead of R{prices_round})."
                )
                if snap:
                    st.caption(f"Snapshot archived: {snap}")
                for w in drv_res.warnings:
                    st.warning(f"Drivers: {w}")
                for w in ctor_res.warnings:
                    st.warning(f"Constructors: {w}")

    st.markdown("---")
    st.markdown("##### Transfer allowance for this week")
    st.caption(
        "Set this before clicking **Generate** so transfer recommendations use the correct free-transfer allowance."
    )
    tf1, tf2 = st.columns(2)
    with tf1:
        manual_free = st.number_input(
            "Free transfers available now",
            min_value=0,
            max_value=10,
            value=int(team.get("free_transfers", 2)),
            step=1,
            key="manual_free_transfers_now",
        )
    with tf2:
        manual_banked = st.number_input(
            "Banked transfers available now",
            min_value=0,
            max_value=10,
            value=int(team.get("banked_transfers", 0)),
            step=1,
            key="manual_banked_transfers_now",
        )
    if st.button("Apply transfer allowance", key="apply_transfer_allowance"):
        cfg_now = get_working_config()
        ct = cfg_now.setdefault("current_team", {})
        ct["free_transfers"] = int(manual_free)
        ct["banked_transfers"] = int(manual_banked)
        set_working_config(cfg_now)
        st.success(
            f"Updated current team transfer state: free={int(manual_free)}, banked={int(manual_banked)}."
        )

with tabs[1]:
    text = _csv_input("race results", "race_res", _RACE_EXAMPLE)
    if st.button("Save race results", key="save_race"):
        res = ingest_race_results(text, PROJECT_ROOT, results_round, cfg=get_working_config())
        if res.ok:
            st.success(f"Saved {res.rows} drivers' race results for R{results_round} → {res.saved_path}")
            for w in res.warnings:
                st.warning(w)
            if res.parsed is not None and not res.parsed.empty:
                st.dataframe(res.parsed.head(10), use_container_width=True)
        else:
            for e in res.errors:
                st.error(e)

# ---------------------------------------------------------------------------
# 3. Refresh model (optional but recommended after each race)
# ---------------------------------------------------------------------------
st.header("3. Refresh model (optional)")

_model_path = PROJECT_ROOT / "data" / "processed" / "models" / "fantasy_model.joblib"
_features_path = PROJECT_ROOT / "data" / "processed" / "features.parquet"


def _file_age(p: "os.PathLike[str]") -> str:
    p = PROJECT_ROOT / p if not str(p).startswith("/") else p
    if not os.path.exists(p):
        return "missing"
    mtime = dt.datetime.fromtimestamp(os.path.getmtime(p))
    age_days = (dt.datetime.now() - mtime).days
    return f"{mtime.strftime('%Y-%m-%d')} ({age_days} day{'s' if age_days != 1 else ''} old)"


_model_age = _file_age(_model_path)
_features_age = _file_age(_features_path)

stale = "missing" in (_model_age, _features_age) or (
    "day" in _model_age and int(_model_age.split("(")[1].split(" ")[0]) > 7
)
status_line = f"Model last trained: **{_model_age}** · Features last built: **{_features_age}**"
if stale:
    st.warning(f"{status_line} — consider retraining before generating.")
else:
    st.caption(status_line)

st.caption(
    "Retraining re-pulls 2026 race results from FastF1 and updates the model, "
    "so predictions for the upcoming round incorporate everything that's happened so far. "
    "Expect 5–15 minutes the first time you do it after several races; subsequent runs "
    "are faster because FastF1 caches."
)

rt1, rt2 = st.columns([1, 2])
with rt1:
    if st.button("Retrain model with latest data", key="btn_retrain"):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        try:
            with st.status("Retraining model (pulling latest data + rebuilding features + training)…", expanded=True) as status:
                proc = subprocess.run(
                    [__import__("sys").executable, "scripts/retrain.py"],
                    cwd=str(PROJECT_ROOT), env=env,
                    capture_output=True, text=True,
                )
                tail = (proc.stdout or "")[-4000:] + "\n" + (proc.stderr or "")[-2000:]
                st.code(tail)
                if proc.returncode == 0:
                    status.update(label="Retrain complete.", state="complete")
                    st.session_state.pop("wizard_recommendation", None)
                    st.session_state.pop("wizard_mode", None)
                    st.success("Model updated. Click Generate below to use the new predictions.")
                else:
                    status.update(label=f"Retrain failed (exit {proc.returncode}).", state="error")
        except Exception as e:
            st.error(f"Retrain failed: {e}")
with rt2:
    st.caption(
        "Tip: the retrain script is also runnable from the CLI as "
        "`PYTHONPATH=. python scripts/retrain.py` — useful if you'd rather kick it off "
        "in a terminal and keep the wizard responsive."
    )


# ---------------------------------------------------------------------------
# 4. Generate recommendation
# ---------------------------------------------------------------------------
st.header("4. Recommendation")

col_gen, col_info = st.columns([1, 3])
with col_gen:
    if st.button("Generate", type="primary", use_container_width=True, key="gen_rec"):
        cfg_now = update_weather_override(
            get_working_config(),
            int(round_number),
            float(rain),
            str(notes),
            temperature_c=float(temp_c),
        )
        set_working_config(cfg_now)
        try:
            with st.spinner("Running model + optimizer…"):
                round_out = recommend_round(cfg=cfg_now, round_number=int(round_number))
                if int(round_number) == 1:
                    st.session_state["wizard_mode"] = "initial"
                    st.session_state["wizard_recommendation"] = round_out
                else:
                    transfer_out = recommend_transfers(
                        cfg=cfg_now,
                        predictions_path=round_out["predictions_path"],
                        season_year=int(season.get("year", 2026)),
                        round_number=int(round_number),
                    )
                    st.session_state["wizard_mode"] = "transfers"
                    st.session_state["wizard_recommendation"] = {
                        "round_out": round_out,
                        "transfer_out": transfer_out,
                    }
        except FileNotFoundError as e:
            st.error(f"Missing artifact: {e}. Run the data pipeline + train the model first (see README).")
            st.stop()
        except Exception as e:
            st.error(f"Recommendation failed: {e}")
            st.stop()
with col_info:
    st.caption(
        "Round 1 → suggests a fresh 5+2 lineup. "
        "Every other round → suggests transfers from your current team within your free-transfer allowance."
    )


def _render_initial(round_out: dict) -> None:
    rec = round_out["recommendation"]
    st.subheader(f"Suggested initial team — R{rec['round_number']}")
    cA, cB, cC = st.columns(3)
    with cA:
        st.metric("Total cost", f"£{rec['total_cost']:.1f}M")
    with cB:
        st.metric("Expected points", f"{rec['expected_points_next_race']:.1f}")
    with cC:
        st.metric("DRS Boost", rec["drs_boost"])

    drivers = rec["drivers"]
    constructors = rec["constructors"]
    drivers_cfg = cfg.get("prices", {}).get("drivers", {})
    constructors_cfg = cfg.get("prices", {}).get("constructors", {})

    rows = []
    for d in drivers:
        meta = drivers_cfg.get(d, {})
        rows.append({"Driver": d, "Name": meta.get("name", ""), "Team": meta.get("team", ""), "Price (£M)": meta.get("price", "")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    crows = []
    for c in constructors:
        meta = constructors_cfg.get(c, {})
        crows.append({"Constructor": c, "Name": meta.get("name", ""), "Price (£M)": meta.get("price", "")})
    st.dataframe(pd.DataFrame(crows), use_container_width=True, hide_index=True)


def _render_transfers(payload: dict) -> None:
    transfer_out = payload["transfer_out"]
    rec = transfer_out["recommendation"]
    drivers_in = transfer_out["drivers_in"]
    drivers_out = transfer_out["drivers_out"]
    ctors_in = transfer_out["constructors_in"]
    ctors_out = transfer_out["constructors_out"]
    free_alw = transfer_out["free_transfer_allowance"]
    n_trans = transfer_out["num_transfers"]
    penalty = transfer_out["transfer_penalty_points"]

    st.subheader(f"Suggested transfers — R{rec['round_number']}")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Transfers", f"{n_trans} / {free_alw} free")
    with m2:
        st.metric("Penalty", f"-{penalty:.0f} pts" if penalty else "0 pts")
    with m3:
        st.metric("Expected pts", f"{rec['expected_points_next_race']:.1f}")
    with m4:
        st.metric("Team cost", f"£{rec['total_cost']:.1f}M")

    if not drivers_in and not drivers_out and not ctors_in and not ctors_out:
        st.info("Model says: **hold** — no transfers worth making this week.")
    else:
        if drivers_in or drivers_out:
            st.markdown("##### Drivers")
            io = max(len(drivers_in), len(drivers_out))
            for i in range(io):
                left = drivers_out[i] if i < len(drivers_out) else "—"
                right = drivers_in[i] if i < len(drivers_in) else "—"
                left_meta = cfg.get("prices", {}).get("drivers", {}).get(left, {})
                right_meta = cfg.get("prices", {}).get("drivers", {}).get(right, {})
                st.markdown(
                    f"- **OUT** `{left}` ({left_meta.get('name', '')}, £{left_meta.get('price', '?')}M)  "
                    f"→  **IN** `{right}` ({right_meta.get('name', '')}, £{right_meta.get('price', '?')}M)"
                )
        if ctors_in or ctors_out:
            st.markdown("##### Constructors")
            io = max(len(ctors_in), len(ctors_out))
            for i in range(io):
                left = ctors_out[i] if i < len(ctors_out) else "—"
                right = ctors_in[i] if i < len(ctors_in) else "—"
                st.markdown(f"- **OUT** `{left}`  →  **IN** `{right}`")

    st.markdown("##### Resulting team")
    drivers = rec["drivers"]
    constructors = rec["constructors"]
    drivers_cfg = cfg.get("prices", {}).get("drivers", {})
    constructors_cfg = cfg.get("prices", {}).get("constructors", {})
    rows = []
    for d in drivers:
        meta = drivers_cfg.get(d, {})
        rows.append({"Driver": d, "Name": meta.get("name", ""), "Team": meta.get("team", ""), "Price (£M)": meta.get("price", "")})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    crows = []
    for c in constructors:
        meta = constructors_cfg.get(c, {})
        crows.append({"Constructor": c, "Name": meta.get("name", ""), "Price (£M)": meta.get("price", "")})
    st.dataframe(pd.DataFrame(crows), use_container_width=True, hide_index=True)

    st.markdown("##### DRS Boost")
    drs = rec["drs_boost"]
    drs_meta = drivers_cfg.get(drs, {})
    st.markdown(
        f"Recommended: **{drs}** ({drs_meta.get('name', '')}). "
        f"DRS Boost doubles the chosen driver's full weekend score (qualifying + race + sprint if applicable)."
    )

    st.markdown("##### Chip decision (max 1 per weekend)")
    chips_left = list(team.get("chips_remaining", []) or [])
    # Predictions parquet gives us per-driver expected points — needed to name a
    # target driver for chips like extra_drs_boost (which applies to a single driver).
    preds_df = None
    preds_path = payload.get("round_out", {}).get("predictions_path")
    if preds_path:
        try:
            preds_df = pd.read_parquet(preds_path)
        except Exception:
            preds_df = None
    decision = _chip_decision(
        chips_left=chips_left,
        transfer_out=transfer_out,
        rain_prob=float(rain),
        is_sprint=int(round_number) in set(season.get("sprint_rounds", [])),
        predictions_df=preds_df,
    )
    if decision is None:
        if not chips_left:
            st.info("**Hold** — no chips remaining.")
        else:
            st.info(
                f"**Don't play a chip this weekend.** None of your remaining chips "
                f"({', '.join(chips_left)}) clears the recommendation threshold for {format_round_label(calendar, int(round_number), short=True)}."
            )
    else:
        chip, score, rationale = decision
        st.success(f"**Play `{chip}` this weekend** (confidence {score}/100). {rationale}")
        other_chips = [c for c in chips_left if c != chip]
        if other_chips:
            st.caption(f"Holding: {', '.join(other_chips)}")


def _chip_decision(
    chips_left: list[str],
    transfer_out: dict[str, Any],
    rain_prob: float,
    is_sprint: bool,
    predictions_df: pd.DataFrame | None = None,
) -> tuple[str, int, str] | None:
    """Score each remaining chip 0-100; return the best if any clears the threshold.

    Threshold is intentionally cautious (60+) because chips are scarce — better
    to hold than to burn on a marginal weekend. Returns (chip, score, rationale)
    or None if nothing recommended.
    """
    if not chips_left:
        return None

    rec_obj = transfer_out.get("recommendation", {}) or {}
    n_trans = int(transfer_out.get("num_transfers", 0))
    free_alw = int(transfer_out.get("free_transfer_allowance", 0))
    hits_needed = max(0, n_trans - free_alw)  # transfers over the free allowance
    expected_pts = float(rec_obj.get("expected_points_next_race", 0.0))

    scores: dict[str, tuple[int, str]] = {}
    chips_set = {c.lower(): c for c in chips_left}

    # no_negative: scales with rain probability (DNF risk insurance, penalty is -20/driver)
    if "no_negative" in chips_set:
        s = int(min(100, rain_prob * 130))  # 50% rain → 65; 80% → 100
        if s >= 60:
            scores[chips_set["no_negative"]] = (
                s, f"Rain probability {rain_prob:.0%} means real DNF risk — chip prevents the -20pt hit per retirement."
            )

    # extra_drs_boost: adds a SECOND DRS slot at 3× alongside the regular 2× slot.
    # Two drivers get boosted that weekend. Optimal assignment: 3× on the team's
    # top predicted scorer, 2× on the team's second-highest.
    if "extra_drs_boost" in chips_set and is_sprint:
        team_drivers = list(rec_obj.get("drivers", []) or [])
        target_3x: str | None = None
        target_3x_pts: float | None = None
        target_2x: str | None = None
        target_2x_pts: float | None = None
        if predictions_df is not None and team_drivers:
            team_preds = (
                predictions_df[predictions_df["driver_code"].isin(team_drivers)]
                .sort_values("y_pred", ascending=False)
                .reset_index(drop=True)
            )
            if len(team_preds) >= 1:
                target_3x = str(team_preds.iloc[0]["driver_code"])
                target_3x_pts = float(team_preds.iloc[0]["y_pred"])
            if len(team_preds) >= 2:
                target_2x = str(team_preds.iloc[1]["driver_code"])
                target_2x_pts = float(team_preds.iloc[1]["y_pred"])
        if not target_3x:
            target_3x = str(rec_obj.get("drs_boost", "") or "?")

        def _fmt(code: str | None, pts: float | None) -> str:
            if not code:
                return "?"
            return f"`{code}` ({pts:.1f} pts)" if pts is not None else f"`{code}`"

        rationale = (
            f"Sprint weekend — extra DRS Boost adds a second boost slot. "
            f"Play **3× on {_fmt(target_3x, target_3x_pts)}** (top scorer), "
            f"**2× on {_fmt(target_2x, target_2x_pts)}** (second highest). "
            "Multipliers compound across qualifying + sprint + race."
        )
        scores[chips_set["extra_drs_boost"]] = (70, rationale)

    # wildcard: free unlimited transfers — worth it if you'd take 4+ hits to rebuild
    if "wildcard" in chips_set and hits_needed >= 4:
        s = min(100, 60 + hits_needed * 5)
        scores[chips_set["wildcard"]] = (
            s, f"Optimal rebuild requires {hits_needed} hits beyond free transfers — wildcard saves {hits_needed*10}+ pts in penalties."
        )

    # limitless: ignore budget for one race — needs a clear "dream team" case
    # Hard to detect from current outputs; require strong expected swing as proxy.
    # Skipped for now — would need a separate optimization run without budget cap.

    # autopilot / final_fix: situational, hard to model — leave as "hold" by default.

    if not scores:
        return None
    best = max(scores.items(), key=lambda kv: kv[1][0])
    chip, (score, rationale) = best
    return chip, score, rationale


payload = st.session_state.get("wizard_recommendation")
mode = st.session_state.get("wizard_mode")
if payload and mode == "initial":
    _render_initial(payload)
elif payload and mode == "transfers":
    _render_transfers(payload)
else:
    st.caption("Click _Generate_ above to see this week's recommendation.")


# ---------------------------------------------------------------------------
# 4. Lock in
# ---------------------------------------------------------------------------
st.header("5. Lock in")

if not payload:
    st.caption("Generate a recommendation first.")
else:
    if mode == "initial":
        rec = payload["recommendation"]
    else:
        rec = payload["transfer_out"]["recommendation"]

    locked_drivers = list(rec["drivers"])
    locked_constructors = list(rec["constructors"])
    rec_drs = rec["drs_boost"]

    # DRS override — model's pick is only as good as its predictions, so let the
    # user swap to any driver on the team if their human read disagrees.
    drs_idx = locked_drivers.index(rec_drs) if rec_drs in locked_drivers else 0
    locked_drs = st.selectbox(
        f"DRS Boost driver (model recommends `{rec_drs}`)",
        options=locked_drivers,
        index=drs_idx,
        format_func=lambda d: f"{d} — {cfg.get('prices', {}).get('drivers', {}).get(d, {}).get('name', '')}",
        help="The model picks the driver with the highest predicted score for this race. Override if your read disagrees.",
    )
    if locked_drs != rec_drs:
        st.caption(f"_Overriding model pick: `{rec_drs}` → `{locked_drs}`_")

    lk1, lk2 = st.columns(2)
    with lk1:
        budget_after = st.number_input(
            "Budget remaining after this lock-in (£M)",
            min_value=0.0, max_value=200.0, value=float(team.get("budget", 0.0)), step=0.1,
        )
        free_after = st.number_input(
            "Free transfers next round",
            min_value=0, max_value=10, value=int(team.get("free_transfers", 2)), step=1,
        )
    with lk2:
        banked_after = st.number_input(
            "Banked transfers",
            min_value=0, max_value=10, value=int(team.get("banked_transfers", 0)), step=1,
        )
        chips_used = st.multiselect(
            "Chips used this week (max 1)",
            options=team.get("chips_remaining", []) or [],
            default=[],
            max_selections=1,
        )

    chip_details = ""
    if chips_used:
        chip = chips_used[0]
        if chip == "extra_drs_boost":
            placeholder = "e.g. 3× on VER, 2× on PER"
        elif chip == "wildcard":
            placeholder = "e.g. Rebuilt entire team — sold SAI/BEA/LAW, bought ANT/HAM/HAD"
        elif chip == "limitless":
            placeholder = "e.g. Picked all top-tier drivers — VER + RUS + NOR + PIA + LEC, Mercedes + Ferrari"
        elif chip == "no_negative":
            placeholder = "e.g. Played for the wet Spa weekend"
        elif chip == "final_fix":
            placeholder = "e.g. Swapped HAD for ALO after Saturday qualifying"
        elif chip == "autopilot":
            placeholder = "e.g. Auto-DRS to highest scorer (no manual pick needed)"
        else:
            placeholder = "Describe how you played the chip"
        chip_details = st.text_input(
            f"How was the **{chip}** chip played?",
            value="",
            placeholder=placeholder,
            help="Free-text notes — saved to history.csv so you can reference later.",
        )

    lockin_notes = st.text_input("Notes (optional, shown in visitor view)", value="")

    if st.button("Lock in this team", type="primary", key="lockin"):
        new_cfg = update_current_team(
            get_working_config(),
            drivers=locked_drivers,
            constructors=locked_constructors,
            drs_boost=locked_drs,
            budget=float(budget_after),
            free_transfers=int(free_after),
            banked_transfers=int(banked_after),
        )
        # Move chips from remaining to used
        ct = new_cfg.setdefault("current_team", {})
        used_now = list(ct.get("chips_used", []) or [])
        rem_now = [c for c in (ct.get("chips_remaining", []) or []) if c not in chips_used]
        used_now.extend(chips_used)
        ct["chips_used"] = used_now
        ct["chips_remaining"] = rem_now
        set_working_config(new_cfg)

        hist_csv_path = append_lockin(
            project_root=PROJECT_ROOT,
            round_number=int(round_number),
            drivers=locked_drivers,
            constructors=locked_constructors,
            drs_boost=locked_drs,
            chips_used=chips_used,
            budget_after=float(budget_after),
            free_transfers_after=int(free_after),
            banked_transfers_after=int(banked_after),
            notes=lockin_notes,
            chip_details=chip_details,
        )
        st.success(f"Locked in. History updated at {hist_csv_path}.")

        # Auto-PR (config.yaml + history.csv) if GitHub creds are configured
        gh = github_settings_from_secrets()
        if gh.get("token") and gh["token"] != "ghp_xxx":
            base_cfg = load_config_file()
            updated_yaml = dump_config_yaml(new_cfg)
            diff = generate_config_diff(base_cfg, new_cfg)
            files_to_pr: dict[str, str] = {"config.yaml": updated_yaml}
            if hist_csv_path.exists():
                files_to_pr["data/fantasy/history.csv"] = hist_csv_path.read_text()
            with st.spinner("Opening PR with config + history update…"):
                pr = propose_files_pr(
                    files=files_to_pr,
                    title=f"Lock in R{int(round_number)} team",
                    body=f"Auto-PR from This Week wizard.\n\n```diff\n{diff[:3000]}\n```",
                    branch_prefix="lockin",
                    settings=gh,
                )
            if pr.ok:
                st.success(f"PR opened: {pr.pr_url}")
            else:
                st.warning(f"PR write-back failed: {pr.message}")
        else:
            st.caption("GitHub credentials not configured — history saved locally only. (Add `GITHUB_TOKEN` to `.streamlit/secrets.toml` to auto-PR.)")

        # If we have race results for the previous round, surface what your team scored
        scored = compute_team_points_for_round(
            project_root=PROJECT_ROOT,
            round_number=max(1, int(round_number) - 1),
            drivers=team.get("drivers", []),
            constructors=team.get("constructors", []),
            drs_boost=team.get("drs_boost"),
        )
        if scored:
            st.markdown("##### Last round's actual points")
            sessions = ", ".join(sorted(scored.get("session_results_paths", {}).keys()))
            if sessions:
                st.caption(f"Included sessions: {sessions}")
            st.caption("DRS is not re-applied here (avoids double counting vs official scored totals).")
            st.metric("Total driver points scored", f"{scored['total_driver_points']:.1f}")
            st.dataframe(pd.DataFrame(scored["drivers"]), use_container_width=True, hide_index=True)

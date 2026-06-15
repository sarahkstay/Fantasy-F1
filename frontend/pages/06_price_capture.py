from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from frontend.components import inject_theme
from frontend.state import get_working_config, is_owner, require_auth, set_working_config
from src.ui_services import ingest_constructor_prices, ingest_driver_prices, save_price_snapshot
from src.ui_services.price_capture_service import parse_price_video


require_auth()

if not is_owner():
    inject_theme()
    st.title("Price Capture")
    st.warning("This page is for the team principal only.")
    st.stop()

inject_theme()
st.title("Price Capture")
st.caption("Upload a mobile screen recording of the price list, review OCR output, then apply prices.")

cfg = get_working_config()

st.header("1. Upload recording")
video_file = st.file_uploader(
    "Upload screen recording (.mp4/.mov)",
    type=["mp4", "mov", "m4v"],
    key="price_capture_video",
    help="Record a slow scroll through drivers and constructors price lists.",
)

s1, s2 = st.columns(2)
with s1:
    sample_every_s = st.slider(
        "Frame sample interval (seconds)",
        min_value=0.2,
        max_value=1.2,
        value=0.45,
        step=0.05,
    )
with s2:
    min_ocr_score = st.slider(
        "Minimum OCR confidence",
        min_value=0.2,
        max_value=0.9,
        value=0.35,
        step=0.05,
    )

if st.button("Parse recording", type="primary", disabled=(video_file is None)):
    if video_file is None:
        st.warning("Upload a video first.")
    else:
        with st.spinner("Extracting frames and OCR text..."):
            out = parse_price_video(
                video_bytes=video_file.getvalue(),
                cfg=cfg,
                sample_every_s=float(sample_every_s),
                min_ocr_score=float(min_ocr_score),
            )
        st.session_state["price_capture_out"] = out
        st.success("Parsing complete. Review below before applying.")

out = st.session_state.get("price_capture_out")
if out:
    rows = out.get("rows", pd.DataFrame())
    meta = out.get("meta", {})
    unmatched = out.get("unmatched_lines", [])

    st.header("2. Review extracted prices")
    if rows.empty:
        st.warning("No candidate prices found. Try a clearer/slower recording.")
    else:
        target_total = int(len((cfg.get("prices", {}).get("drivers", {}) or {})) + len((cfg.get("prices", {}).get("constructors", {}) or {})))
        detected_codes = set(rows["code"].astype(str)) if "code" in rows.columns else set()
        coverage_count = int(len(detected_codes))
        coverage_pct = (100.0 * coverage_count / max(1, target_total))

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Frames scanned", int(meta.get("frames_scanned", 0)))
        with c2:
            st.metric("Rows detected", int(len(rows)))
        with c3:
            st.metric("Needs review", int(rows["needs_review"].sum() if "needs_review" in rows.columns else 0))
        st.progress(min(1.0, max(0.0, coverage_pct / 100.0)))
        st.caption(f"Coverage: **{coverage_count}/{target_total} assets detected** ({coverage_pct:.0f}%).")

        show_review_only = st.checkbox("Show only needs review", value=False, key="price_capture_show_review_only")

        editable = rows.copy()
        if show_review_only and "needs_review" in editable.columns:
            editable = editable[editable["needs_review"]].copy()
        editable["price"] = pd.to_numeric(editable["price"], errors="coerce")
        edited = st.data_editor(
            editable,
            use_container_width=True,
            hide_index=True,
            column_config={
                "asset_type": st.column_config.TextColumn("Type", disabled=True),
                "code": st.column_config.TextColumn("Code", disabled=True),
                "name": st.column_config.TextColumn("Name", disabled=True),
                "price": st.column_config.NumberColumn("Price", min_value=0.0, step=0.1),
                "confidence": st.column_config.NumberColumn("Confidence", disabled=True),
                "frames_seen": st.column_config.NumberColumn("Frames", disabled=True),
                "samples": st.column_config.NumberColumn("Samples", disabled=True),
                "raw_example": st.column_config.TextColumn("OCR Example", disabled=True),
                "needs_review": st.column_config.CheckboxColumn("Needs Review"),
            },
            key="price_capture_editor",
        )

        st.session_state["price_capture_rows"] = edited

        if unmatched:
            with st.expander("Unmatched OCR lines (optional debug)"):
                st.code("\n".join(unmatched[:100]))

        st.header("3. Apply to working config")
        if st.button("Apply extracted prices", key="apply_extracted_prices"):
            apply_rows = st.session_state.get("price_capture_rows", edited)
            if apply_rows is None or len(apply_rows) == 0:
                st.warning("No rows to apply.")
            else:
                payload_rows = []
                for _, r in apply_rows.iterrows():
                    t = str(r.get("asset_type", "")).strip()
                    name = str(r.get("name", "")).strip()
                    try:
                        price = float(r.get("price"))
                    except Exception:
                        continue
                    if not t or not name:
                        continue
                    payload_rows.append({"type": t, "name": name, "price_million_usd": price})
                csv_text = pd.DataFrame(payload_rows).to_csv(index=False)

                cfg_now = get_working_config()
                drv_res = ingest_driver_prices(cfg_now, csv_text)
                if not drv_res.ok:
                    for e in drv_res.errors:
                        st.error(f"Drivers: {e}")
                else:
                    cfg_now = drv_res.updated_config
                    ctor_res = ingest_constructor_prices(cfg_now, csv_text)
                    if not ctor_res.ok:
                        for e in ctor_res.errors:
                            st.error(f"Constructors: {e}")
                    else:
                        set_working_config(ctor_res.updated_config)
                        snap = save_price_snapshot(csv_text, PROJECT_ROOT, int(cfg.get("weather_override", {}).get("next_race_round", 1)), "ocr_video")
                        st.success(
                            f"Applied prices: {drv_res.rows} drivers + {ctor_res.rows} constructors."
                        )
                        if snap:
                            st.caption(f"Snapshot archived: {snap}")
                        for w in drv_res.warnings:
                            st.warning(f"Drivers: {w}")
                        for w in ctor_res.warnings:
                            st.warning(f"Constructors: {w}")

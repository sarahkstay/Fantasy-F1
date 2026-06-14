from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process


PRICE_RE = re.compile(r"(?<!\d)(\d{1,2}(?:\.\d{1,3})?)(?!\d)")


def _build_asset_catalog(cfg: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    drivers = cfg.get("prices", {}).get("drivers", {}) or {}
    ctors = cfg.get("prices", {}).get("constructors", {}) or {}

    driver_candidates: dict[str, dict[str, Any]] = {}
    for code, meta in drivers.items():
        name = str(meta.get("name", "")).strip()
        if not name:
            continue
        keys = {name.lower(), code.lower(), name.split()[-1].lower()}
        for k in keys:
            driver_candidates[k] = {"asset_type": "Driver", "code": str(code).upper(), "name": name}

    ctor_candidates: dict[str, dict[str, Any]] = {}
    for cid, meta in ctors.items():
        name = str(meta.get("name", "")).strip()
        if not name:
            continue
        keys = {
            name.lower(),
            str(cid).lower(),
            str(cid).lower().replace("_", " "),
            name.lower().replace(" racing", "").replace(" f1 team", "").strip(),
        }
        for k in keys:
            ctor_candidates[k] = {"asset_type": "Constructor", "code": str(cid).lower(), "name": name}

    return driver_candidates, ctor_candidates


def _best_match(raw_name: str, candidates: dict[str, dict[str, Any]]) -> tuple[dict[str, Any] | None, float]:
    key = raw_name.lower().strip()
    if not key:
        return None, 0.0
    if key in candidates:
        return candidates[key], 1.0
    out = process.extractOne(key, list(candidates.keys()), scorer=fuzz.WRatio)
    if not out:
        return None, 0.0
    matched_key, score, _ = out
    if score < 74:
        return None, score / 100.0
    return candidates[matched_key], score / 100.0


def _iter_sampled_frames(video_path: Path, sample_every_s: float) -> list[tuple[int, np.ndarray]]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("Could not read video file.")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_step = max(1, int(round(float(fps) * max(0.1, sample_every_s))))
    frames: list[tuple[int, np.ndarray]] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % frame_step == 0:
            frames.append((idx, frame))
        idx += 1
    cap.release()
    return frames


def _frame_to_ocr_input(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return gray


def parse_price_video(
    video_bytes: bytes,
    cfg: dict[str, Any],
    sample_every_s: float = 0.45,
    min_ocr_score: float = 0.35,
) -> dict[str, Any]:
    """Extract candidate price rows from a screen recording.

    Returns resolved rows + unmatched lines for manual review.
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "rapidocr_onnxruntime is not installed. Add it to requirements and redeploy."
        ) from e

    driver_catalog, ctor_catalog = _build_asset_catalog(cfg)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        tmp.write(video_bytes)
        tmp_path = Path(tmp.name)

    try:
        ocr = RapidOCR()
        frames = _iter_sampled_frames(tmp_path, sample_every_s=sample_every_s)
        if not frames:
            return {"rows": pd.DataFrame(), "unmatched_lines": [], "meta": {"frames_scanned": 0}}

        raw_hits: list[dict[str, Any]] = []
        unmatched_lines: list[str] = []

        for frame_idx, frame in frames:
            img = _frame_to_ocr_input(frame)
            ocr_out = ocr(img)
            if isinstance(ocr_out, tuple):
                result = ocr_out[0]
            else:
                result = ocr_out
            if not result:
                continue

            for item in result:
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                text = str(item[1]).strip()
                score = float(item[2] or 0.0)
                if score < float(min_ocr_score):
                    continue
                if len(text) < 3:
                    continue

                p = PRICE_RE.search(text.replace(",", "."))
                if not p:
                    continue
                try:
                    price = float(p.group(1))
                except ValueError:
                    continue
                if price < 3.0 or price > 60.0:
                    continue

                name_part = text[: p.start()].strip(" -:|$")
                if len(name_part) < 2:
                    unmatched_lines.append(text)
                    continue

                d_match, d_conf = _best_match(name_part, driver_catalog)
                c_match, c_conf = _best_match(name_part, ctor_catalog)
                match = None
                match_conf = 0.0
                if d_match and d_conf >= c_conf:
                    match = d_match
                    match_conf = d_conf
                elif c_match:
                    match = c_match
                    match_conf = c_conf

                if not match:
                    unmatched_lines.append(text)
                    continue

                raw_hits.append(
                    {
                        "frame_idx": int(frame_idx),
                        "raw_text": text,
                        "raw_name": name_part,
                        "asset_type": match["asset_type"],
                        "code": match["code"],
                        "name": match["name"],
                        "price": float(price),
                        "ocr_score": float(score),
                        "name_match_conf": float(match_conf),
                        "combined_conf": float((score + match_conf) / 2.0),
                    }
                )
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    if not raw_hits:
        return {
            "rows": pd.DataFrame(),
            "unmatched_lines": unmatched_lines[:120],
            "meta": {"frames_scanned": len(frames)},
        }

    hits = pd.DataFrame(raw_hits)
    grouped = []
    for (asset_type, code, name), g in hits.groupby(["asset_type", "code", "name"], sort=False):
        g = g.sort_values("combined_conf", ascending=False)
        top = g.iloc[0]
        grouped.append(
            {
                "asset_type": asset_type,
                "code": code,
                "name": name,
                "price": round(float(top["price"]), 3),
                "confidence": round(float(top["combined_conf"]), 3),
                "frames_seen": int(g["frame_idx"].nunique()),
                "samples": int(len(g)),
                "raw_example": str(top["raw_text"]),
                "needs_review": bool(float(top["combined_conf"]) < 0.72),
            }
        )
    rows = pd.DataFrame(grouped).sort_values(["asset_type", "code"]).reset_index(drop=True)
    return {
        "rows": rows,
        "unmatched_lines": unmatched_lines[:200],
        "meta": {"frames_scanned": len(frames), "raw_hits": len(raw_hits)},
    }

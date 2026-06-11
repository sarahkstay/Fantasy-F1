"""
Train a fantasy-points prediction model from features.parquet.

Uses config for engine (lightgbm/xgboost), hyperparameters, and backtest years.
Temporal split: train on data before test_year, evaluate on test_year.
Saves the trained model and optional backtest metrics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from src.utils.logging import get_logger

log = get_logger(__name__)

# Feature columns used for modelling (must exist in features.parquet)
FEATURE_COLS = [
    # Track numeric
    "circuit_overtake_difficulty", "circuit_drs_zones", "circuit_safety_car_prob", "is_sprint_round",
    # Contextual
    "era_weight", "rainfall_flag",
    # Driver rolling
    "driver_rolling_pts_3", "driver_rolling_pts_5", "driver_avg_finish_at_circuit",
    "driver_overtake_rate", "driver_dnf_rate",
    # Driver skill (persistent across team changes — teammate-delta rolling avg)
    "driver_skill_residual",
    # Driver cold-start
    "driver_prev_season_avg_pts", "driver_prev_season_avg_finish",
    "driver_prev_season_dnf_rate", "driver_prev_season_overtake_rate",
    "driver_prev_season_races", "driver_is_cold_start", "driver_early_round_flag",
    "driver_cold_start_pressure",
    # Team — data-derived current-year baseline (replaces manual development_score)
    "team_year_baseline",
    # Team pitstop
    "team_fastest_pitstop_avg", "team_avg_pitstop_avg",
    # Team cold-start
    "team_prev_season_avg_pts", "team_prev_season_avg_finish",
    "team_prev_season_dnf_rate", "team_prev_season_races",
    # Car-track interactions
    "team_pts_at_circuit_type_hist", "team_pts_at_circuit_type_season",
    "team_pts_at_downforce_hist", "team_pts_at_downforce_season",
    "team_circuit_type_delta", "team_season_rounds_so_far",
    "driver_pts_at_circuit_type_hist", "driver_pts_at_circuit_type_season",
    "driver_pts_at_downforce_hist", "driver_pts_at_downforce_season",
]
CAT_COLS = ["circuit_type", "circuit_downforce", "season_phase"]
TARGET = "fantasy_points_driver"


def _prepare_xy(
    df: pd.DataFrame,
    feature_cols: list[str],
    cat_cols: list[str],
    target: str,
) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    """Build X, y and final feature list. One-hot encode categoricals."""
    use_cols = [c for c in feature_cols if c in df.columns]
    cat_present = [c for c in cat_cols if c in df.columns]
    X = df[use_cols].copy()
    for c in cat_present:
        if X[c].dtype == "object" or X[c].dtype.name == "category":
            dums = pd.get_dummies(X[c], prefix=c, drop_first=True, dtype=float)
            X = pd.concat([X.drop(columns=[c]), dums], axis=1)
    X = X.astype(float).fillna(0)
    final_features = list(X.columns)
    y = df[target] if target in df.columns else pd.Series(dtype=float)
    return X, y, final_features


def _fit_model(
    engine: str,
    hp: dict[str, Any],
    X: pd.DataFrame,
    y: pd.Series,
):
    if engine == "lightgbm":
        import lightgbm as lgb

        model = lgb.LGBMRegressor(**hp, verbosity=-1, random_state=42)
        model.fit(X, y)
        return model
    if engine == "xgboost":
        import xgboost as xgb

        model = xgb.XGBRegressor(**hp, random_state=42)
        model.fit(X, y)
        return model
    raise ValueError(f"Unknown model engine: {engine}")


def train_model(
    features_path: str | Path,
    config: dict[str, Any] | None = None,
    test_year: int | None = None,
    train_start_year: int | None = None,
    model_dir: str | Path | None = None,
) -> dict[str, Any]:
    """
    Load features, temporal split, train model, save to model_dir.

    Args:
        features_path: Path to features.parquet.
        config: Config dict (for model.engine, model.hyperparameters, backtest).
        test_year: Year to use as holdout (default: config backtest.primary_test_year).
        train_start_year: First year for training (default: config backtest.train_start_year).
        model_dir: Where to save model and metadata (default: data/processed/models).

    Returns:
        Dict with keys: model, feature_names, train_metrics, test_metrics, test_year.
    """
    from src.config import load_config

    if config is None:
        config = load_config()
    features_path = Path(features_path)
    if not features_path.exists():
        raise FileNotFoundError(f"Features not found: {features_path}")

    backtest_cfg = config.get("backtest", {})
    test_year = test_year or backtest_cfg.get("primary_test_year", 2025)
    train_start_year = train_start_year or backtest_cfg.get("train_start_year", 2020)
    model_dir = Path(model_dir or backtest_cfg.get("model_dir") or "data/processed/models")
    model_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(features_path)
    if TARGET not in df.columns:
        raise ValueError(f"Target column '{TARGET}' not in features.parquet")
    if "year" not in df.columns:
        raise ValueError("Features must contain 'year' for temporal split")

    # Race rows only for training (one row per driver per race)
    df = df[df["session_type"] == "race"].copy()
    if df.empty:
        raise ValueError("No race rows in features")

    train_df = df[(df["year"] >= train_start_year) & (df["year"] < test_year)]
    test_df = df[df["year"] == test_year]

    # If no temporal split (e.g. only one year of data), split by round or by row
    if train_df.empty and not df.empty:
        rounds = sorted(pd.Series(df["round"].dropna().unique()).astype(int))
        if len(rounds) >= 2:
            split_idx = max(1, int(len(rounds) * 0.8))
            train_rounds, test_rounds = set(rounds[:split_idx]), set(rounds[split_idx:])
            train_df = df[df["round"].isin(train_rounds)]
            test_df = df[df["round"].isin(test_rounds)]
            log.info("Single-year fallback: train on rounds %s, test on %s", sorted(train_rounds), sorted(test_rounds))
        else:
            # Single round: random 80/20 split by row so we still get a model and train metrics
            from sklearn.model_selection import train_test_split
            train_idx, test_idx = train_test_split(df.index, test_size=0.2, random_state=42)
            train_df = df.loc[train_idx]
            test_df = df.loc[test_idx]
            log.info("Single-round fallback: 80/20 row split for train/test")
    elif train_df.empty:
        raise ValueError(f"No training data for years {train_start_year}..{test_year-1}")
    if test_df.empty:
        log.warning("No test data for year %s; evaluation will be empty", test_year)

    all_feature_cols = FEATURE_COLS + CAT_COLS
    X_train, y_train, feature_names = _prepare_xy(train_df, all_feature_cols, CAT_COLS, TARGET)
    X_test, y_test, _ = _prepare_xy(test_df, all_feature_cols, CAT_COLS, TARGET)
    # Align test features to train (in case of missing categories)
    for c in feature_names:
        if c not in X_test.columns:
            X_test[c] = 0
    X_test = X_test[feature_names]

    engine = config.get("model", {}).get("engine", "lightgbm")
    hp = config.get("model", {}).get("hyperparameters", {}).get(engine, {})

    # Eval model (temporal split) for holdout diagnostics.
    eval_model = _fit_model(engine, hp, X_train, y_train)

    train_pred = eval_model.predict(X_train)
    train_mae = float(np.abs(train_pred - y_train).mean())
    train_rmse = float(np.sqrt(((train_pred - y_train) ** 2).mean()))
    train_metrics = {"mae": train_mae, "rmse": train_rmse}

    if not test_df.empty and len(y_test) > 0:
        test_pred = eval_model.predict(X_test)
        test_mae = float(np.abs(test_pred - y_test).mean())
        test_rmse = float(np.sqrt(((test_pred - y_test) ** 2).mean()))
        test_metrics = {"mae": test_mae, "rmse": test_rmse}
        log.info("Test year %s: MAE=%.2f, RMSE=%.2f", test_year, test_mae, test_rmse)
    else:
        test_metrics = {}

    # Refit production model on all data available since train_start_year so the
    # model keeps learning as the season progresses (while still reporting holdout
    # diagnostics from the temporal split above).
    prod_df = df[df["year"] >= train_start_year].copy()
    X_prod, y_prod, prod_feature_names = _prepare_xy(prod_df, all_feature_cols, CAT_COLS, TARGET)
    model = _fit_model(engine, hp, X_prod, y_prod)

    # Save production model
    import joblib

    model_path = model_dir / "fantasy_model.joblib"
    joblib.dump({"model": model, "feature_names": prod_feature_names, "engine": engine}, model_path)
    log.info("Saved model to %s", model_path)
    (model_dir / "feature_names.txt").write_text("\n".join(prod_feature_names))

    return {
        "model": model,
        "feature_names": prod_feature_names,
        "train_metrics": train_metrics,
        "test_metrics": test_metrics,
        "test_year": test_year,
    }

"""
Behavioral biometrics feature processor.

Processes signals from the mobile SDK (typing speed, touch pressure, session age)
and computes a confidence score indicating whether the current session behaviour
matches the customer's historical baseline.

These signals are optional — scoring degrades gracefully (confidence=0.5) when
the mobile app does not send them.

Expected SDK payload (passed as `biometrics` dict in the score request):
    {
        "typing_speed_wpm": 42.5,         # words per minute on PIN/amount entry
        "touch_pressure_avg": 0.68,       # 0.0–1.0 normalized touch pressure
        "touch_pressure_std": 0.12,       # variability
        "swipe_velocity_px_s": 800.0,     # average swipe velocity
        "session_age_seconds": 145.0,     # seconds since app opened
        "orientation_changes": 2,         # how many times phone was rotated
        "accelerometer_variance": 0.03,   # motion noise (stationary vs walking)
    }
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict

# Per-customer biometric baselines stored in memory (production: use Redis or DB column)
# key: (tenant_id, customer_id) → baseline dict + timestamp
_BIOMETRIC_BASELINES: Dict[tuple, tuple[Dict[str, float], float]] = {}
_BASELINE_TTL_SECONDS = 86400  # 24 hours


def _safe_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def extract_biometric_features(
    biometrics: Dict[str, Any] | None,
    tenant_id: str,
    customer_id: str,
) -> Dict[str, float]:
    """
    Convert raw biometric signals into normalised features for the fraud model.

    Returns a dict with keys:
        biometric_confidence        – 0.0 (suspicious) to 1.0 (matches baseline)
        typing_speed_deviation      – |current - baseline| / baseline, capped at 2.0
        touch_pressure_deviation    – same for pressure
        session_age_seconds         – raw session age (capped at 3600s)
        biometric_signals_present   – 1.0 if SDK sent data, 0.0 if not
    """
    if not biometrics:
        return {
            "biometric_confidence": 0.5,
            "typing_speed_deviation": 0.0,
            "touch_pressure_deviation": 0.0,
            "session_age_seconds": 0.0,
            "biometric_signals_present": 0.0,
        }

    typing_wpm = _safe_float(biometrics.get("typing_speed_wpm"), 0.0)
    pressure_avg = _safe_float(biometrics.get("touch_pressure_avg"), 0.0)
    pressure_std = _safe_float(biometrics.get("touch_pressure_std"), 0.0)
    swipe_vel = _safe_float(biometrics.get("swipe_velocity_px_s"), 0.0)
    session_age = min(_safe_float(biometrics.get("session_age_seconds"), 0.0), 3600.0)
    accel_var = _safe_float(biometrics.get("accelerometer_variance"), 0.0)

    cache_key = (str(tenant_id), str(customer_id))
    cached = _BIOMETRIC_BASELINES.get(cache_key)
    now = time.time()

    if cached is None or (now - cached[1]) > _BASELINE_TTL_SECONDS:
        # No baseline yet — store current signals and return neutral confidence
        baseline: Dict[str, float] = {
            "typing_speed_wpm": typing_wpm,
            "touch_pressure_avg": pressure_avg,
            "swipe_velocity_px_s": swipe_vel,
            "session_count": 1.0,
        }
        _BIOMETRIC_BASELINES[cache_key] = (baseline, now)
        # Evict if cache gets too large
        if len(_BIOMETRIC_BASELINES) > 50_000:
            _BIOMETRIC_BASELINES.clear()
        return {
            "biometric_confidence": 0.5,
            "typing_speed_deviation": 0.0,
            "touch_pressure_deviation": 0.0,
            "session_age_seconds": session_age,
            "biometric_signals_present": 1.0,
        }

    baseline, _ts = cached

    # Compute deviations from baseline
    baseline_typing = max(baseline.get("typing_speed_wpm", 1.0), 1.0)
    baseline_pressure = max(baseline.get("touch_pressure_avg", 0.01), 0.01)
    baseline_swipe = max(baseline.get("swipe_velocity_px_s", 1.0), 1.0)

    typing_dev = abs(typing_wpm - baseline_typing) / baseline_typing if typing_wpm > 0 else 0.0
    pressure_dev = abs(pressure_avg - baseline_pressure) / baseline_pressure if pressure_avg > 0 else 0.0
    swipe_dev = abs(swipe_vel - baseline_swipe) / baseline_swipe if swipe_vel > 0 else 0.0

    typing_dev = min(typing_dev, 2.0)
    pressure_dev = min(pressure_dev, 2.0)
    swipe_dev = min(swipe_dev, 2.0)

    # Composite confidence: lower = more anomalous
    # Each deviation of >50% from baseline reduces confidence significantly
    weighted_deviation = 0.4 * typing_dev + 0.4 * pressure_dev + 0.2 * swipe_dev
    confidence = max(0.0, min(1.0, 1.0 - weighted_deviation))

    # Short session (< 5s) with high-value transaction = suspicious
    if session_age < 5.0 and session_age > 0:
        confidence = max(0.0, confidence - 0.2)

    # Update baseline with exponential moving average
    alpha = 0.1  # slow update: baseline is sticky
    new_baseline = {
        "typing_speed_wpm": (1 - alpha) * baseline_typing + alpha * (typing_wpm or baseline_typing),
        "touch_pressure_avg": (1 - alpha) * baseline_pressure + alpha * (pressure_avg or baseline_pressure),
        "swipe_velocity_px_s": (1 - alpha) * baseline_swipe + alpha * (swipe_vel or baseline_swipe),
        "session_count": baseline.get("session_count", 1.0) + 1.0,
    }
    _BIOMETRIC_BASELINES[cache_key] = (new_baseline, now)

    return {
        "biometric_confidence": round(confidence, 4),
        "typing_speed_deviation": round(typing_dev, 4),
        "touch_pressure_deviation": round(pressure_dev, 4),
        "session_age_seconds": session_age,
        "biometric_signals_present": 1.0,
    }


def clear_biometric_cache() -> None:
    _BIOMETRIC_BASELINES.clear()

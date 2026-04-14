from __future__ import annotations

import math
from typing import Any


def _sigmoid(v: float) -> float:
    if v >= 0:
        z = math.exp(-v)
        return 1.0 / (1.0 + z)
    z = math.exp(v)
    return z / (1.0 + z)


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def apply_calibration(score: float, *, method: str, params: dict[str, Any] | None) -> float:
    m = (method or "none").lower()
    p = dict(params or {})
    x = _clip01(score)

    if m in {"none", ""}:
        return x
    if m == "platt":
        a = float(p.get("a", 1.0))
        b = float(p.get("b", 0.0))
        return _clip01(_sigmoid(a * x + b))
    if m == "isotonic":
        points = p.get("points") or []
        if not isinstance(points, list) or len(points) < 2:
            return x
        normalized = []
        for pt in points:
            if not isinstance(pt, dict):
                continue
            if "x" not in pt or "y" not in pt:
                continue
            normalized.append((float(pt["x"]), _clip01(float(pt["y"]))))
        if len(normalized) < 2:
            return x
        normalized.sort(key=lambda t: t[0])
        if x <= normalized[0][0]:
            return normalized[0][1]
        if x >= normalized[-1][0]:
            return normalized[-1][1]
        for i in range(1, len(normalized)):
            x0, y0 = normalized[i - 1]
            x1, y1 = normalized[i]
            if x0 <= x <= x1:
                if x1 == x0:
                    return y1
                w = (x - x0) / (x1 - x0)
                return _clip01(y0 + w * (y1 - y0))
        return x
    return x

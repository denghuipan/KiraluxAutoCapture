"""
Contrast clip + scale helpers for image export (H5 training data).
"""
from __future__ import annotations

from typing import Tuple

import numpy as np


def compute_vmin_vmax(
    image: np.ndarray,
    *,
    mode: str = "percent_max",
    vmin_pct: float = 0.0,
    vmax_pct: float = 100.0,
    p_low: float = 1.0,
    p_high: float = 99.0,
) -> Tuple[float, float]:
    """Return (vmin, vmax) for contrast scaling."""
    arr = np.asarray(image, dtype=np.float64)
    if mode == "percentile":
        vmin, vmax = np.percentile(arr, [float(p_low), float(p_high)])
    else:
        pmax = float(arr.max()) if arr.size and arr.max() > 0 else 1.0
        vmin = pmax * float(vmin_pct) / 100.0
        vmax = pmax * float(vmax_pct) / 100.0
    if vmax <= vmin:
        vmax = vmin + 1.0
    return float(vmin), float(vmax)


def apply_vmin_vmax_scale(
    image: np.ndarray,
    *,
    vmin: float,
    vmax: float,
    out_dtype=np.uint16,
) -> np.ndarray:
    """Clip to [vmin, vmax] and linearly scale to full uint16 range."""
    arr = np.asarray(image, dtype=np.float64)
    clipped = np.clip(arr, vmin, vmax)
    scaled = (clipped - vmin) / (vmax - vmin)
    if out_dtype == np.uint16:
        return np.round(scaled * 65535.0).astype(np.uint16)
    return scaled.astype(out_dtype)


def prepare_image_for_h5(image: np.ndarray, cfg: dict) -> Tuple[np.ndarray, float, float]:
    """
    Optionally apply configured vmin/vmax contrast before H5 append.

    Returns (processed_image, vmin, vmax). If contrast disabled, returns
    original image and (nan, nan) for vmin/vmax.
    """
    if not cfg.get("auto_roi_h5_contrast_enabled"):
        return np.asarray(image), float("nan"), float("nan")

    mode = cfg.get("auto_roi_h5_contrast_mode", "percent_max")
    vmin, vmax = compute_vmin_vmax(
        image,
        mode=mode,
        vmin_pct=cfg.get("auto_roi_h5_vmin_pct", 0),
        vmax_pct=cfg.get("auto_roi_h5_vmax_pct", 100),
        p_low=cfg.get("auto_roi_h5_p_low", 1.0),
        p_high=cfg.get("auto_roi_h5_p_high", 99.0),
    )
    out = apply_vmin_vmax_scale(image, vmin=vmin, vmax=vmax)
    return out, vmin, vmax

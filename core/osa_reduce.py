"""
OSA spectrum dimensionality reduction — notebook ``reduce_dim_smooth``.
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

try:
    from scipy.signal import savgol_filter
except ImportError:  # pragma: no cover
    savgol_filter = None


def reduce_dim_smooth(
    wl: np.ndarray,
    mag: np.ndarray,
    *,
    num_points: int = 300,
    filter_window: int = 31,
    polyorder: int = 3,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Savitzky-Golay smooth then uniform index downsample to ``num_points``.

    Identical logic to ``End-facet single peak data.ipynb``.
    """
    wl = np.asarray(wl, dtype=np.float64)
    mag = np.asarray(mag, dtype=np.float64)
    if wl.size == 0 or mag.size == 0:
        raise ValueError("Empty wavelength or magnitude array")
    n = min(wl.size, mag.size)
    wl = wl[:n]
    mag = mag[:n]

    if savgol_filter is not None and len(mag) > filter_window:
        win = int(filter_window)
        if win % 2 == 0:
            win += 1
        poly = min(int(polyorder), win - 1)
        mag_smooth = savgol_filter(mag, win, poly)
    else:
        mag_smooth = mag

    if num_points <= 0:
        raise ValueError("num_points must be positive")
    if num_points == 1:
        indices = np.array([0], dtype=int)
    else:
        indices = np.linspace(0, len(wl) - 1, num_points).astype(int)

    return wl[indices], mag_smooth[indices]


def mask_wavelength_range(
    wl: np.ndarray,
    mag: np.ndarray,
    wl_min: float,
    wl_max: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Keep samples inside ``[wl_min, wl_max]`` nm."""
    mask = (wl >= wl_min) & (wl <= wl_max)
    if not np.any(mask):
        raise ValueError(f"No OSA samples in range [{wl_min}, {wl_max}] nm")
    return wl[mask], mag[mask]

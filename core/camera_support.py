"""
Thorlabs Kiralux camera helpers.

ROI format: (x1, y1, x2, y2) — upper-left and lower-right corners,
NOT (x0, y0, width, height).  Must be set via camera.roi BEFORE arm().
"""
from __future__ import annotations

from typing import Sequence, Tuple, Union

import numpy as np

RoiTuple = Tuple[int, int, int, int]

# Kiralux maximum exposure (ms) — matches TLCamera SDK limit used in UI
EXPOSURE_MAX_MS = 22806.0
EXPOSURE_MIN_MS = 0.03


def normalize_roi(roi: Union[RoiTuple, Sequence[int], object]) -> RoiTuple:
    """Convert SDK ROI NamedTuple or sequence to (x1, y1, x2, y2)."""
    if hasattr(roi, "upper_left_x_pixels"):
        return (
            int(roi.upper_left_x_pixels),
            int(roi.upper_left_y_pixels),
            int(roi.lower_right_x_pixels),
            int(roi.lower_right_y_pixels),
        )
    x1, y1, x2, y2 = roi
    return int(x1), int(y1), int(x2), int(y2)


def roi_dimensions(roi: Union[RoiTuple, Sequence[int], object]) -> Tuple[int, int]:
    """Return (width, height) for ROI (x1, y1, x2, y2)."""
    x1, y1, x2, y2 = normalize_roi(roi)
    return x2 - x1, y2 - y1


def set_camera_roi(camera, roi: Sequence[int]) -> RoiTuple:
    """
    Set hardware ROI on the camera (before arm()).

    Returns the actual ROI read back from the SDK (may differ slightly
    from the requested values on some models).
    """
    camera.roi = normalize_roi(roi)
    return normalize_roi(camera.roi)


def frame_to_image(image_buffer, roi: Union[RoiTuple, Sequence[int], object]) -> np.ndarray:
    """Reshape a 1-D frame buffer into (height, width) using ROI dimensions."""
    w, h = roi_dimensions(roi)
    buf = np.copy(image_buffer)
    if buf.ndim == 1:
        expected = w * h
        if buf.size != expected:
            raise ValueError(
                f"Frame size {buf.size} does not match ROI {w}x{h}={expected}"
            )
        return buf.reshape(h, w)
    return buf

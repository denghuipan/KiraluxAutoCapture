"""
ROI finder — locates the brightest signal window using a max-sum sliding window.

Algorithm:
1. Slide a (signal_height × signal_width) window across the image.
2. Compute the sum of pixel values within each window position.
3. Find the position with the maximum sum.
4. Center a larger (outer_height × outer_width) crop around that position.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np


class RoiTuple:
    """Represents the found ROI region."""
    __slots__ = ("x1", "y1", "width", "height", "score")

    def __init__(self, x1: int, y1: int, width: int, height: int, score: float):
        self.x1 = x1
        self.y1 = y1
        self.width = width
        self.height = height
        self.score = score

    def as_xywh(self):
        """Return (x, y, width, height) tuple."""
        return (self.x1, self.y1, self.width, self.height)

    def __repr__(self):
        return (
            f"RoiTuple(x1={self.x1}, y1={self.y1}, "
            f"width={self.width}, height={self.height}, score={self.score:.0f})"
        )


class RoiFinderError(Exception):
    pass


def find_roi(
    image: np.ndarray,
    outer_width: int,
    outer_height: int,
    *,
    signal_width: int = 380,
    signal_height: int = 35,
) -> RoiTuple:
    """
    Locate the best ROI in ``image``.

    Parameters
    ----------
    image : np.ndarray
        2-D grayscale image (H, W).
    outer_width, outer_height : int
        Size of the final crop to return.
    signal_width, signal_height : int
        Size of the sliding window used to find the brightest signal.

    Returns
    -------
    RoiTuple
        Object with (x1, y1, width, height, score) of the outer crop region.
    """
    if image.ndim != 2:
        raise RoiFinderError(f"Expected 2-D image, got {image.ndim}-D")

    h, w = image.shape
    if outer_width > w or outer_height > h:
        raise RoiFinderError(
            f"Outer crop ({outer_width}x{outer_height}) larger than image ({w}x{h})"
        )
    if signal_width > w or signal_height > h:
        raise RoiFinderError(
            f"Signal window ({signal_width}x{signal_height}) larger than image ({w}x{h})"
        )

    # Use integral image for fast sliding window sum
    integral = np.cumsum(np.cumsum(image.astype(np.float64), axis=0), axis=1)

    # Pad integral with zeros on top and left for easier indexing
    integral = np.pad(integral, ((1, 0), (1, 0)), mode="constant")

    # Compute sum for every (signal_height x signal_width) window
    # Sum at (r, c) = integral[r+h, c+w] - integral[r, c+w] - integral[r+h, c] + integral[r, c]
    row_max = h - signal_height
    col_max = w - signal_width

    # Vectorized computation
    sums = (
        integral[signal_height : signal_height + row_max + 1, signal_width : signal_width + col_max + 1]
        - integral[0 : row_max + 1, signal_width : signal_width + col_max + 1]
        - integral[signal_height : signal_height + row_max + 1, 0 : col_max + 1]
        + integral[0 : row_max + 1, 0 : col_max + 1]
    )

    # Find position of maximum sum
    best_r, best_c = np.unravel_index(np.argmax(sums), sums.shape)

    # best_r, best_c are the top-left corner of the signal window
    signal_center_x = best_c + signal_width // 2
    signal_center_y = best_r + signal_height // 2

    # Center the outer crop around the signal center
    x1 = max(0, signal_center_x - outer_width // 2)
    y1 = max(0, signal_center_y - outer_height // 2)

    # Clamp to image boundaries
    x1 = min(x1, w - outer_width)
    y1 = min(y1, h - outer_height)

    score = float(sums[best_r, best_c])

    return RoiTuple(x1=int(x1), y1=int(y1), width=outer_width, height=outer_height, score=score)


def crop_xywh(image: np.ndarray, xywh: Sequence[int]) -> np.ndarray:
    """
    Crop ``image`` to the region defined by (x, y, width, height).

    Parameters
    ----------
    image : np.ndarray
        2-D grayscale image (H, W).
    xywh : tuple/list
        (x, y, width, height) of the crop region.

    Returns
    -------
    np.ndarray
        Cropped image.
    """
    x, y, w, h = xywh
    return image[int(y) : int(y) + int(h), int(x) : int(x) + int(w)].copy()

"""Unified sample labels for paired image / OSA H5 export."""
from __future__ import annotations

from typing import Optional


def make_sample_label(
    loop_i: int,
    loop_j: int,
    *,
    round_idx: Optional[int] = None,
) -> str:
    """
    Build a label shared by cropped images and OSA spectra.

    Format: ``round{RR}_loop{loop_i}_{j}``  e.g. ``round01_loop5_3``
    """
    r = int(round_idx) if round_idx is not None else 1
    return f"round{r:02d}_loop{int(loop_i)}_{int(loop_j)}"

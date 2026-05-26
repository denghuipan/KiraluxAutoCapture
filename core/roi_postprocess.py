"""
Optional inline ROI crop after each captured frame.

Uses the same algorithm as ``roi_processor`` (notebook max-sum window),
loaded without package-name conflicts via importlib.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Dict, Optional

import numpy as np


def _roi_processor_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "roi_processor"
    return Path(__file__).resolve().parents[2] / "roi_processor"


def _load_sibling_module(module_name: str, rel_path: str):
    path = _roi_processor_root() / rel_path
    if not path.is_file():
        raise ImportError(f"ROI processor module not found: {path}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_finder = None
_image_io = None


def _finder():
    global _finder
    if _finder is None:
        _finder = _load_sibling_module("kiralux_roi_finder", "core/roi_finder.py")
    return _finder


def _image_io():
    global _image_io
    if _image_io is None:
        _image_io = _load_sibling_module("kiralux_image_io", "core/image_io.py")
    return _image_io


class RoiPostprocessError(Exception):
    pass


def postprocess_config_from_cfg(cfg: dict) -> Optional[dict]:
    """Return post-process settings dict if ROI crop and/or H5 export is enabled."""
    if not (cfg.get("auto_roi_enabled") or cfg.get("auto_roi_h5_enabled")):
        return None
    save_files = bool(cfg.get("auto_roi_enabled"))
    return {
        "signal_width": int(cfg.get("auto_roi_signal_w", 380)),
        "signal_height": int(cfg.get("auto_roi_signal_h", 35)),
        "outer_width": int(cfg.get("auto_roi_outer_w", 400)),
        "outer_height": int(cfg.get("auto_roi_outer_h", 40)),
        "p_low": float(cfg.get("auto_roi_p_low", 1.0)),
        "p_high": float(cfg.get("auto_roi_p_high", 99.0)),
        "save_tif": save_files,
        "save_png": save_files and bool(cfg.get("auto_roi_save_png", True)),
        "subdir": cfg.get("auto_roi_subdir", "cropped") or "cropped",
        "crop_suffix": cfg.get("auto_roi_crop_suffix", "_crop"),
        "preview_suffix": cfg.get("auto_roi_preview_suffix", "_preview"),
    }


def postprocess_frame(
    image: np.ndarray,
    raw_path: str,
    *,
    out_dir: str,
    settings: dict,
) -> Dict[str, str]:
    """
    Run ROI algorithm on ``image``, save crop TIFF (+ optional PNG preview).

    Returns dict with keys ``tif``, and optionally ``png``.
    """
    finder = _finder()
    io = _image_io()

    outer_w = settings["outer_width"]
    outer_h = settings["outer_height"]
    signal_w = settings["signal_width"]
    signal_h = settings["signal_height"]

    roi = finder.find_roi(
        image,
        outer_w,
        outer_h,
        signal_width=signal_w,
        signal_height=signal_h,
    )
    cropped = finder.crop_xywh(image, roi.as_xywh())
    if cropped.shape != (outer_h, outer_w):
        raise RoiPostprocessError(
            f"Crop shape {cropped.shape} != expected ({outer_h}, {outer_w})"
        )

    subdir = settings.get("subdir", "cropped")
    crop_dir = os.path.join(out_dir, subdir) if subdir else out_dir
    os.makedirs(crop_dir, exist_ok=True)

    stem = Path(raw_path).stem
    crop_suffix = settings.get("crop_suffix", "_crop")
    preview_suffix = settings.get("preview_suffix", "_preview")
    result = {"cropped": cropped, "roi": roi}

    if settings.get("save_tif", True):
        tif_path = os.path.join(crop_dir, f"{stem}{crop_suffix}.tif")
        io.save_tiff(tif_path, cropped)
        result["tif"] = tif_path
    if settings.get("save_png", True):
        png_path = os.path.join(crop_dir, f"{stem}{preview_suffix}.png")
        io.save_preview_png(
            png_path,
            cropped,
            p_low=settings.get("p_low", 1.0),
            p_high=settings.get("p_high", 99.0),
        )
        result["png"] = png_path
    return result

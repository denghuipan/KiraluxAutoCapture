"""
Image I/O utilities for ROI postprocessing.

Provides TIFF saving and PNG preview generation with contrast stretching.
"""
from __future__ import annotations

import numpy as np


class ImageIOError(Exception):
    pass


class ImageIO:
    """Handle saving of TIFF and PNG images."""

    def save_tiff(self, path: str, image: np.ndarray) -> None:
        """
        Save ``image`` as a 16-bit TIFF file.

        Parameters
        ----------
        path : str
            Output file path.
        image : np.ndarray
            2-D image array.
        """
        try:
            import tifffile
            tifffile.imwrite(path, image.astype(np.uint16))
        except ImportError:
            # Fallback: write raw binary
            image.astype(np.uint16).tofile(path)

    def save_preview_png(
        self,
        path: str,
        image: np.ndarray,
        *,
        p_low: float = 1.0,
        p_high: float = 99.0,
    ) -> None:
        """
        Save ``image`` as an 8-bit PNG with percentile-based contrast stretch.

        Parameters
        ----------
        path : str
            Output file path.
        image : np.ndarray
            2-D image array (any numeric dtype).
        p_low, p_high : float
            Lower and upper percentile values for contrast stretching.
        """
        try:
            from PIL import Image
        except ImportError:
            raise ImageIOError("PIL (Pillow) is required for PNG saving")

        # Compute contrast stretch limits
        vmin = np.percentile(image, p_low)
        vmax = np.percentile(image, p_high)

        if vmax <= vmin:
            # Degenerate case: constant image
            img_8bit = np.zeros_like(image, dtype=np.uint8)
        else:
            # Clip and normalize to 0-255
            clipped = np.clip(image.astype(np.float64), vmin, vmax)
            img_8bit = ((clipped - vmin) / (vmax - vmin) * 255.0).astype(np.uint8)

        img = Image.fromarray(img_8bit, mode="L")
        img.save(path, "PNG")

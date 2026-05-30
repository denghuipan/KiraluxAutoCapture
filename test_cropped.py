"""
Test script for the ROI cropped functionality.

Generates synthetic Gaussian blob images (500x100) and runs the full
ROI postprocessing pipeline to verify it works correctly.
"""
import os
import sys
import tempfile
import shutil

import numpy as np

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def generate_gaussian_blob_image(
    width: int = 500,
    height: int = 100,
    blob_center_x: float = None,
    blob_center_y: float = None,
    blob_sigma_x: float = 30.0,
    blob_sigma_y: float = 8.0,
    blob_amplitude: float = 5000.0,
    background: float = 50.0,
    noise_sigma: float = 10.0,
    seed: int = 42,
) -> np.ndarray:
    """
    Generate a synthetic image with a Gaussian blob on a noisy background.

    Parameters
    ----------
    width, height : int
        Image dimensions.
    blob_center_x, blob_center_y : float or None
        Center of the Gaussian blob. If None, placed randomly.
    blob_sigma_x, blob_sigma_y : float
        Standard deviations of the blob in x and y.
    blob_amplitude : float
        Peak intensity of the blob.
    background : float
        Mean background level.
    noise_sigma : float
        Standard deviation of Gaussian noise.
    seed : int
        Random seed for reproducibility.

    Returns
    -------
    np.ndarray
        2-D image array of shape (height, width), dtype=np.uint16.
    """
    rng = np.random.default_rng(seed)

    if blob_center_x is None:
        blob_center_x = rng.uniform(width * 0.2, width * 0.8)
    if blob_center_y is None:
        blob_center_y = rng.uniform(height * 0.2, height * 0.8)

    y, x = np.mgrid[0:height, 0:width]

    # Gaussian blob
    blob = blob_amplitude * np.exp(
        -((x - blob_center_x) ** 2 / (2 * blob_sigma_x ** 2)
          + (y - blob_center_y) ** 2 / (2 * blob_sigma_y ** 2))
    )

    # Background + noise
    image = background + blob + rng.normal(0, noise_sigma, size=(height, width))
    image = np.clip(image, 0, 65535).astype(np.uint16)

    return image, blob_center_x, blob_center_y


def test_cropped_functionality():
    """Run the full ROI postprocessing pipeline on synthetic images."""
    from core.roi_postprocess import (
        postprocess_config_from_cfg,
        postprocess_frame,
        RoiPostprocessError,
    )

    # Create a temporary output directory
    tmpdir = tempfile.mkdtemp(prefix="roi_crop_test_")
    print(f"Output directory: {tmpdir}")

    # Test configuration
    cfg = {
        "auto_roi_enabled": True,
        "auto_roi_save_png": True,
        "auto_roi_subdir": "cropped",
        "auto_roi_signal_w": 380,
        "auto_roi_signal_h": 35,
        "auto_roi_outer_w": 400,
        "auto_roi_outer_h": 40,
        "auto_roi_p_low": 1.0,
        "auto_roi_p_high": 99.0,
        "auto_roi_show_preview": True,
        "auto_roi_h5_enabled": False,
    }

    settings = postprocess_config_from_cfg(cfg)
    if not settings:
        print("ERROR: postprocess_config_from_cfg returned None")
        return False

    print("Postprocess settings:")
    for k, v in settings.items():
        print(f"  {k}: {v}")
    print()

    # Generate and process multiple test images
    num_tests = 5
    success_count = 0

    for i in range(num_tests):
        print(f"--- Test {i+1}/{num_tests} ---")

        # Generate synthetic image
        image, true_cx, true_cy = generate_gaussian_blob_image(
            width=500,
            height=100,
            seed=42 + i,
        )
        print(f"  Generated image: shape={image.shape}, dtype={image.dtype}")
        print(f"  Blob center (ground truth): x={true_cx:.1f}, y={true_cy:.1f}")
        print(f"  Image stats: min={image.min()}, max={image.max()}, mean={image.mean():.1f}")

        # Create a fake raw path
        raw_path = os.path.join(tmpdir, f"test_image_{i}.tif")

        try:
            result = postprocess_frame(
                image,
                raw_path,
                out_dir=tmpdir,
                settings=settings,
            )

            cropped = result["cropped"]
            roi = result["roi"]

            print(f"  ROI found: x1={roi.x1}, y1={roi.y1}, w={roi.width}, h={roi.height}, score={roi.score:.0f}")
            print(f"  Cropped image: shape={cropped.shape}, dtype={cropped.dtype}")
            print(f"  Cropped stats: min={cropped.min()}, max={cropped.max()}, mean={cropped.mean():.1f}")

            if result.get("tif"):
                print(f"  TIFF saved: {result['tif']}")
            if result.get("png"):
                print(f"  PNG saved: {result['png']}")

            # Verify cropped dimensions
            expected_shape = (settings["outer_height"], settings["outer_width"])
            if cropped.shape == expected_shape:
                print(f"  [OK] Cropped shape matches expected: {expected_shape}")
            else:
                print(f"  [WARN] Cropped shape {cropped.shape} != expected {expected_shape}")

            # Check that files were created
            tif_exists = result.get("tif") and os.path.exists(result["tif"])
            png_exists = result.get("png") and os.path.exists(result["png"])
            if tif_exists and png_exists:
                print(f"  [OK] Both TIFF and PNG files created successfully")
            else:
                print(f"  [WARN] Missing files: TIFF={tif_exists}, PNG={png_exists}")

            success_count += 1
            print(f"  PASSED Test {i+1}")

        except RoiPostprocessError as exc:
            print(f"  FAILED Test {i+1} (RoiPostprocessError): {exc}")
        except Exception as exc:
            print(f"  FAILED Test {i+1} (Exception): {exc}")
            import traceback
            traceback.print_exc()

        print()

    print("=" * 60)
    print(f"Results: {success_count}/{num_tests} tests passed")

    # List generated files
    cropped_dir = os.path.join(tmpdir, "cropped")
    if os.path.exists(cropped_dir):
        files = os.listdir(cropped_dir)
        print(f"\nFiles in {cropped_dir}:")
        for f in sorted(files):
            fpath = os.path.join(cropped_dir, f)
            size = os.path.getsize(fpath)
            print(f"  {f} ({size:,} bytes)")

    print(f"\nOutput directory (kept for inspection): {tmpdir}")

    return success_count == num_tests


if __name__ == "__main__":
    print("ROI Cropped Functionality Test")
    print("=" * 60)
    success = test_cropped_functionality()
    sys.exit(0 if success else 1)

"""
Incremental HDF5 writers for paired image / OSA training datasets.
"""
from __future__ import annotations

import os
import threading
from typing import Optional, Tuple

import numpy as np

try:
    import h5py
except ImportError:  # pragma: no cover
    h5py = None


class H5AppendError(Exception):
    pass


class _BaseAppendWriter:
    def __init__(self, path: str, *, data_key: str):
        if h5py is None:
            raise H5AppendError("h5py is required — pip install h5py")
        self.path = path
        self.data_key = data_key
        self._lock = threading.Lock()
        self._file: Optional["h5py.File"] = None
        self._count = 0
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.flush()
                self._file.close()
                self._file = None

    def _open(self):
        if self._file is None:
            self._file = h5py.File(self.path, "a")

    def _ensure_meta(self, n: int):
        self._open()
        f = self._file
        str_dt = h5py.string_dtype(encoding="utf-8")
        if "labels" not in f:
            f.create_dataset(
                "labels",
                shape=(n,),
                maxshape=(None,),
                dtype=str_dt,
                compression="gzip",
            )
            f.create_dataset(
                "filenames",
                shape=(n,),
                maxshape=(None,),
                dtype=str_dt,
                compression="gzip",
            )
        else:
            f["labels"].resize((n,))
            f["filenames"].resize((n,))


class ImageH5Writer(_BaseAppendWriter):
    """Append cropped 2-D frames to ``image`` dataset."""

    def __init__(self, path: str):
        super().__init__(path, data_key="image")

    def append(
        self,
        image: np.ndarray,
        label: str,
        filename: str,
    ) -> int:
        arr = np.asarray(image)
        if arr.ndim != 2:
            raise H5AppendError(f"Expected 2-D image, got shape {arr.shape}")

        with self._lock:
            self._open()
            f = self._file
            idx = self._count
            n = idx + 1

            if self.data_key not in f:
                f.create_dataset(
                    self.data_key,
                    shape=(n,) + arr.shape,
                    maxshape=(None,) + arr.shape,
                    dtype=arr.dtype,
                    compression="gzip",
                    chunks=True,
                )
            else:
                ds = f[self.data_key]
                if tuple(ds.shape[1:]) != arr.shape:
                    raise H5AppendError(
                        f"Image shape mismatch {arr.shape} vs {tuple(ds.shape[1:])}"
                    )
                if ds.dtype != arr.dtype:
                    arr = arr.astype(ds.dtype, copy=False)
                ds.resize((n,) + arr.shape)

            self._ensure_meta(n)
            f[self.data_key][idx] = arr
            f["labels"][idx] = label
            f["filenames"][idx] = filename
            self._count = n
            f.flush()
            return idx


class OsaH5Writer(_BaseAppendWriter):
    """Append reduced 1-D spectra to ``spectrum`` dataset (N, P, 1)."""

    def __init__(self, path: str):
        super().__init__(path, data_key="spectrum")

    def append(
        self,
        spectrum: np.ndarray,
        wavelength: np.ndarray,
        label: str,
        filename: str,
    ) -> int:
        spec = np.asarray(spectrum, dtype=np.float32).reshape(-1)
        wl = np.asarray(wavelength, dtype=np.float32).reshape(-1)
        if spec.shape != wl.shape:
            raise H5AppendError(
                f"Spectrum/wavelength length mismatch {spec.shape} vs {wl.shape}"
            )

        with self._lock:
            self._open()
            f = self._file
            idx = self._count
            n = idx + 1
            sample = spec.reshape(-1, 1)

            if self.data_key not in f:
                f.create_dataset(
                    self.data_key,
                    shape=(n,) + sample.shape,
                    maxshape=(None,) + sample.shape,
                    dtype=np.float32,
                    compression="gzip",
                    chunks=True,
                )
                f.create_dataset(
                    "wavelength",
                    data=wl,
                    dtype=np.float32,
                    compression="gzip",
                )
            else:
                ds = f[self.data_key]
                if ds.shape[1:] != sample.shape:
                    raise H5AppendError(
                        f"Spectrum shape mismatch {sample.shape} vs {ds.shape[1:]}"
                    )
                if "wavelength" in f:
                    old_wl = f["wavelength"][:]
                    if old_wl.shape != wl.shape or not np.allclose(old_wl, wl, rtol=1e-4, atol=1e-3):
                        raise H5AppendError(
                            "Reduced wavelength axis changed between samples — "
                            "keep OSA settings constant within one H5 file."
                        )
                else:
                    f.create_dataset("wavelength", data=wl, dtype=np.float32)
                ds.resize((n,) + sample.shape)

            self._ensure_meta(n)
            f[self.data_key][idx] = sample
            f["labels"][idx] = label
            f["filenames"][idx] = filename
            self._count = n
            f.flush()
            return idx


def open_image_h5_writer(cfg: dict, base_out_dir: str) -> Optional[ImageH5Writer]:
    if not cfg.get("auto_roi_h5_enabled"):
        return None
    name = cfg.get("auto_roi_h5_filename", "images.h5") or "images.h5"
    path = os.path.join(base_out_dir, name)
    return ImageH5Writer(path)


def open_osa_h5_writer(cfg: dict, base_out_dir: str) -> Optional[OsaH5Writer]:
    if not cfg.get("osa_h5_enabled"):
        return None
    name = cfg.get("osa_h5_filename", "osa_spectra.h5") or "osa_spectra.h5"
    path = os.path.join(base_out_dir, name)
    return OsaH5Writer(path)

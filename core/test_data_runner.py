"""
Automated test-data collection — RF power servo + Kiralux capture.

Independent from LoopRunner; does not affect normal multi-peak training loops.
"""
from __future__ import annotations

import csv
import os
import threading
import time
from datetime import datetime
from typing import List, Optional

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal

from core.pm_meter import PM100DPowerMeter, SimulatedPowerMeter, create_power_meter
from core.power_math import pm_watts_for_target
from core.rf_power_control import (
    RFPowerControlError,
    RFPowerMaxReachedError,
    RFPowerMinReachedError,
    adjust_rf_to_target,
)


class _AcqAbort(Exception):
    pass


def _parse_float_list(text: str) -> List[float]:
    out: List[float] = []
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.append(float(part))
    return out


class TestDataRunner(QThread):
    log_signal = pyqtSignal(str)
    warn_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)
    finished_signal = pyqtSignal(bool)
    camera_frame_signal = pyqtSignal(np.ndarray, str)

    def __init__(self, cfg: dict, nkt_thread=None):
        super().__init__()
        self.cfg = cfg
        self.nkt_thread = nkt_thread
        self._stop_flag = threading.Event()

    def request_stop(self):
        self._stop_flag.set()

    def run(self):
        try:
            self._main()
            self.finished_signal.emit(True)
        except _AcqAbort:
            self.finished_signal.emit(False)
        except RFPowerMinReachedError as exc:
            self.error_signal.emit(str(exc))
            self.finished_signal.emit(False)
        except RFPowerMaxReachedError as exc:
            self.error_signal.emit(str(exc))
            self.finished_signal.emit(False)
        except RFPowerControlError as exc:
            self.error_signal.emit(str(exc))
            self.finished_signal.emit(False)
        except Exception as exc:
            self.error_signal.emit(f"Test data collection failed: {exc}")
            self.finished_signal.emit(False)

    def _main(self):
        cfg = self.cfg
        if not cfg.get("test_data_enabled"):
            self.error_signal.emit("Test data collection is not enabled.")
            raise _AcqAbort

        wavelengths = _parse_float_list(cfg.get("test_wavelengths_nm", ""))
        targets_dbm = _parse_float_list(cfg.get("test_target_dbm_list", ""))
        if not wavelengths:
            self.error_signal.emit("Enter at least one wavelength (nm).")
            raise _AcqAbort
        if not targets_dbm:
            self.error_signal.emit("Enter at least one target power (dBm).")
            raise _AcqAbort

        coupling = float(cfg.get("test_coupling_eff", 1e-5))
        tol_db = float(cfg.get("test_power_tol_db", 0.5))
        initial_amp = int(cfg.get("test_initial_rf", 500))
        min_amp = int(cfg.get("test_rf_min", 10))
        max_amp = int(cfg.get("test_rf_max", 1000))
        laser_settle = float(cfg.get("test_laser_settle_s", 0.5))
        pm_settle = float(cfg.get("test_pm_settle_s", 0.3))
        max_iter = int(cfg.get("test_rf_max_iter", 40))

        out_dir = cfg.get("test_out_dir", ".") or "."
        prefix = cfg.get("test_file_prefix", "test") or "test"
        os.makedirs(out_dir, exist_ok=True)

        exp_ms = float(cfg.get("test_exposure_ms", cfg.get("exposure_time_ms", 0.06)))
        gain = int(cfg.get("test_gain", cfg.get("gain", 0)))
        timeout_ms = int(cfg.get("test_timeout_ms", cfg.get("timeout_ms", 5000)))
        roi = cfg.get("test_roi", cfg.get("roi", (0, 0, 4096, 2160)))
        img_fmt = cfg.get("test_img_format", cfg.get("img_format", "tif"))

        nt = self.nkt_thread
        if nt is None:
            self.error_signal.emit("NKT thread not available.")
            raise _AcqAbort
        if not getattr(nt, "_dll_ready", False):
            detail = getattr(nt, "_dll_import_error", "") or "unknown error"
            from core.nkt_support import _nkt_arch_subdir
            arch = _nkt_arch_subdir()
            self.error_signal.emit(
                f"NKTP_DLL not loaded — {detail}\n"
                f"(Need {arch}-bit NKTPDLL.dll in NKT/NKTPDLL/{arch}/)"
            )
            raise _AcqAbort

        comport_hint = cfg.get("comport", "COM5")
        crystal = int(cfg.get("crystal_num", 0))
        emission = int(cfg.get("emission_percent", 100))

        from core.nkt_support import discover_nkt_modules, set_single_channel
        from core.nkt_support import (
            Extreme_turnON,
            RF_turnON,
            crystal_select,
            nkt_full_shutdown,
        )

        com, extreme, rf, sk, err = nt.call(discover_nkt_modules, comport_hint, 0.5)
        if err or not com:
            self.error_signal.emit(err or "NKT not found — scan ports in Hardware Test tab.")
            raise _AcqAbort
        self.log_signal.emit(f"NKT on {com}  extreme@{extreme}  RF@{rf}")

        sk = sk if sk is not None else -1
        nt.call(Extreme_turnON, com, extreme, emission)
        nt.call(crystal_select, com, rf, sk, crystal)
        nt.call(RF_turnON, com, rf)
        self.log_signal.emit("NKT laser ready.")

        pm = create_power_meter(
            cfg.get("test_pm_backend", "pm100d"),
            visa_resource=cfg.get("test_pm_visa_resource", ""),
            sim_max_w=float(cfg.get("test_pm_sim_max_w", 1.0)),
        )
        try:
            pm.connect()
        except Exception as exc:
            self._nkt_shutdown(nt, com, extreme, rf)
            self.error_signal.emit(f"Power meter connect failed: {exc}")
            raise _AcqAbort

        if isinstance(pm, PM100DPowerMeter):
            idn = pm.idn or pm.resource
            self.log_signal.emit(f"PM100D connected: {idn}")
        elif isinstance(pm, SimulatedPowerMeter):
            self.warn_signal.emit(
                "Using simulated power meter — select PM100D (USB/VISA) for real runs."
            )

        camera = None
        sdk = None
        camera_roi = roi
        try:
            from thorlabs_tsi_sdk.tl_camera import TLCameraSDK
            from core.camera_support import set_camera_roi, frame_to_image

            sdk = TLCameraSDK()
            cams = sdk.discover_available_cameras()
            if not cams:
                raise RuntimeError("No Kiralux camera detected.")
            camera = sdk.open_camera(cams[0])
            camera_roi = set_camera_roi(camera, roi)
            camera.frames_per_trigger_zero_for_unlimited = 0
            camera.image_poll_timeout_ms = timeout_ms
            camera.gain = gain
            camera.arm(2)
            self.log_signal.emit(
                f"Camera ready  exp={exp_ms} ms  gain={gain}  ROI={camera_roi}"
            )
        except Exception as exc:
            pm.close()
            self._nkt_shutdown(nt, com, extreme, rf)
            self.error_signal.emit(f"Camera init failed: {exc}")
            raise _AcqAbort

        log_path = os.path.join(out_dir, cfg.get("test_log_csv", "test_data_log.csv"))
        log_exists = os.path.isfile(log_path)
        log_fields = [
            "timestamp", "step", "wavelength_nm", "target_dbm",
            "pm_reading_W", "coupling_eff", "actual_W", "actual_dbm",
            "rf_amplitude", "exposure_ms", "gain", "filename", "status",
        ]

        total_steps = len(wavelengths) * len(targets_dbm)
        step_n = 0
        rows = []

        def _set_rf(amp: int):
            if isinstance(pm, SimulatedPowerMeter):
                pm.set_rf_hint(amp)
            nt.call(set_single_channel, com, rf, wl, int(amp), 0)

        try:
            with open(log_path, "a", newline="", encoding="utf-8") as log_f:
                writer = csv.DictWriter(log_f, fieldnames=log_fields)
                if not log_exists:
                    writer.writeheader()

                for wl in wavelengths:
                    if self._stop_flag.is_set():
                        self.warn_signal.emit("Stop requested.")
                        raise _AcqAbort

                    self.log_signal.emit(f"══ Wavelength {wl:.3f} nm ══")
                    _set_rf(initial_amp)
                    time.sleep(laser_settle)

                    for target_dbm in targets_dbm:
                        if self._stop_flag.is_set():
                            raise _AcqAbort

                        step_n += 1
                        pct = int(step_n / total_steps * 100)
                        self.progress_signal.emit(
                            pct,
                            f"λ={wl:.1f} nm  target={target_dbm:.1f} dBm  "
                            f"({step_n}/{total_steps})",
                        )
                        pm_need = pm_watts_for_target(target_dbm, coupling)
                        self.log_signal.emit(
                            f"Step {step_n}: target {target_dbm:.2f} dBm "
                            f"(PM ≈ {pm_need:.3e} W @ coupling {coupling:.3e})"
                        )

                        try:
                            result = adjust_rf_to_target(
                                pm.read_power_watts,
                                _set_rf,
                                target_dbm=target_dbm,
                                coupling_efficiency=coupling,
                                initial_amp=initial_amp,
                                min_amp=min_amp,
                                max_amp=max_amp,
                                tolerance_db=tol_db,
                                max_iterations=max_iter,
                                settle_s=laser_settle,
                                pm_settle_s=pm_settle,
                                stop_check=lambda: self._stop_flag.is_set(),
                            )
                        except RFPowerMinReachedError:
                            raise
                        except RFPowerControlError as exc:
                            self.error_signal.emit(str(exc))
                            raise _AcqAbort

                        self.log_signal.emit(
                            f"  RF={result.rf_amplitude}/1000  "
                            f"PM={result.pm_reading_w:.3e} W  "
                            f"actual={result.actual_dbm:.2f} dBm  "
                            f"({result.iterations} iter)"
                        )
                        initial_amp = result.rf_amplitude

                        camera.exposure_time_us = int(exp_ms * 1000)
                        camera.issue_software_trigger()
                        frame = camera.get_pending_frame_or_null()
                        if frame is None:
                            self.error_signal.emit(
                                f"Camera timeout at λ={wl} target={target_dbm} dBm"
                            )
                            raise _AcqAbort

                        buf = frame_to_image(frame.image_buffer, camera_roi)
                        safe = (
                            f"{prefix}_wl{wl:.3f}nm_tgt{target_dbm:.2f}dbm"
                            f"_rf{result.rf_amplitude}.{img_fmt}"
                        )
                        path = os.path.join(out_dir, safe)
                        self._save_frame(buf, path, img_fmt)
                        self.log_signal.emit(f"  Saved {os.path.basename(path)}")

                        info = (
                            f"TEST  λ={wl:.1f}nm  tgt={target_dbm:.1f}dBm  "
                            f"act={result.actual_dbm:.1f}dBm  RF={result.rf_amplitude}"
                        )
                        self.camera_frame_signal.emit(buf, info)

                        row = {
                            "timestamp": datetime.now().isoformat(timespec="seconds"),
                            "step": step_n,
                            "wavelength_nm": wl,
                            "target_dbm": target_dbm,
                            "pm_reading_W": result.pm_reading_w,
                            "coupling_eff": coupling,
                            "actual_W": result.actual_w,
                            "actual_dbm": result.actual_dbm,
                            "rf_amplitude": result.rf_amplitude,
                            "exposure_ms": exp_ms,
                            "gain": gain,
                            "filename": os.path.basename(path),
                            "status": "ok",
                        }
                        writer.writerow(row)
                        log_f.flush()
                        rows.append(row)

        finally:
            if camera is not None:
                try:
                    camera.disarm()
                    camera.dispose()
                except Exception:
                    pass
            if sdk is not None:
                try:
                    sdk.dispose()
                except Exception:
                    pass
            pm.close()
            self._nkt_shutdown(nt, com, extreme, rf)

        self.log_signal.emit(
            f"Test data collection complete — {len(rows)} frames, log → {log_path}"
        )

    @staticmethod
    def _nkt_shutdown(nt, com, extreme, rf):
        from core.nkt_support import nkt_full_shutdown
        try:
            nt.call(nkt_full_shutdown, com, extreme, rf)
        except Exception:
            pass

    @staticmethod
    def _save_frame(buf, path, fmt):
        if fmt == "tif":
            try:
                import tifffile
                tifffile.imwrite(path, buf)
            except ImportError:
                np.save(path.replace(".tif", ".npy"), buf)
        elif fmt == "npy":
            np.save(path, buf)
        else:
            buf.tofile(path)

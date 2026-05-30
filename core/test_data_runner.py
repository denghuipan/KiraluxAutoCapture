"""
Automated test-data collection — RF power servo + Kiralux capture.

Independent from LoopRunner; does not affect normal multi-peak training loops.
"""
from __future__ import annotations

import csv
import json
import math
import os
import socket
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
    servo_rf_to_target,
    servo_rf_to_target_bisect,
)


class _AcqAbort(Exception):
    pass


class LivePowerMonitor(QThread):
    """Continuously read the power meter for live display only.

    Independent of TestDataRunner: it never controls NKT/RF/laser, it just
    opens the meter and streams readings so the operator can see live power
    *before* starting a test collection.
    """
    reading_signal = pyqtSignal(float, float, float, float)
    # t_sec, pm_W, actual_W, actual_dbm
    error_signal = pyqtSignal(str)
    started_signal = pyqtSignal(str)  # connected device description

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg
        self._stop_flag = threading.Event()

    def request_stop(self):
        self._stop_flag.set()

    def run(self):
        from core.power_math import actual_watts_from_pm, watts_to_dbm

        cfg = self.cfg
        coupling = float(cfg.get("test_coupling_eff", 1e-5))
        interval = max(0.001, float(cfg.get("test_pm_settle_s", 0.1)))
        wl = float(cfg.get("live_wavelength_nm", 600.0))

        try:
            pm = create_power_meter(
                cfg.get("test_pm_backend", "pm100d"),
                visa_resource=cfg.get("test_pm_visa_resource", ""),
                sim_max_w=float(cfg.get("test_pm_sim_max_w", 1.0)),
                wavelength_nm=wl,
            )
        except Exception as exc:
            self.error_signal.emit(str(exc))
            return

        try:
            pm.connect()
        except Exception as exc:
            self.error_signal.emit(f"Power meter connect failed: {exc}")
            return

        if isinstance(pm, PM100DPowerMeter):
            try:
                pm.set_wavelength(wl)
            except Exception:
                pass
            self.started_signal.emit(pm.idn or pm.resource)
        elif isinstance(pm, SimulatedPowerMeter):
            self.started_signal.emit("Simulated power meter (development)")

        t0 = time.perf_counter()
        try:
            while not self._stop_flag.is_set():
                try:
                    pm_w = float(pm.read_power_watts())
                except Exception as exc:
                    self.error_signal.emit(f"PM read failed: {exc}")
                    break
                act_w = actual_watts_from_pm(pm_w, coupling)
                act_dbm = watts_to_dbm(act_w)
                if not math.isfinite(act_dbm):
                    act_dbm = -120.0
                self.reading_signal.emit(
                    time.perf_counter() - t0, pm_w, act_w, act_dbm
                )
                self._stop_flag.wait(interval)
        finally:
            try:
                pm.close()
            except Exception:
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
    pm_reading_signal = pyqtSignal(float, int, float, float, float, float, str)
    # t_sec, amp, pm_W, actual_W, actual_dbm, target_dbm, phase
    pm_trace_reset_signal = pyqtSignal(float, float)  # target_dbm, tolerance_db
    osa_spectrum_signal = pyqtSignal(np.ndarray, np.ndarray, str, str)

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

        wl_source = cfg.get("test_wl_source", "manual")

        targets_dbm = _parse_float_list(cfg.get("test_target_dbm_list", ""))
        if not targets_dbm:
            self.error_signal.emit("Enter at least one target power (dBm).")
            raise _AcqAbort

        if wl_source == "loop_tab":
            from core.nkt_support import build_nkt_step_configs
            nkt_step_configs = build_nkt_step_configs(cfg)
            if not nkt_step_configs:
                self.error_signal.emit(
                    "No NKT step configs generated — check Loop Tab settings "
                    "(wavelength range, n_steps, manual channels)."
                )
                raise _AcqAbort
            step_items = []
            for sc in nkt_step_configs:
                wls = sc["wavelengths"]
                center_wl = float(sum(wls) / len(wls)) if wls else 600.0
                step_items.append({"center_wl": center_wl, "multi_cfg": sc})
        else:
            wavelengths = _parse_float_list(cfg.get("test_wavelengths_nm", ""))
            if not wavelengths:
                self.error_signal.emit("Enter at least one wavelength (nm).")
                raise _AcqAbort
            step_items = [{"center_wl": wl, "multi_cfg": None} for wl in wavelengths]

        coupling = float(cfg.get("test_coupling_eff", 1e-5))
        tol_db = float(cfg.get("test_power_tol_db", 0.5))
        min_amp = int(cfg.get("test_rf_min", 10))
        max_amp = int(cfg.get("test_rf_max", 1000))
        laser_settle = float(cfg.get("test_laser_settle_s", 0.5))
        pm_settle = float(cfg.get("test_pm_settle_s", 0.3))
        step_interval_ms = float(cfg.get("test_rf_step_interval_ms", 50.0))
        n_repeats = max(1, int(cfg.get("test_repeats", 1)))

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

        from core.nkt_support import (
            discover_nkt_modules,
            set_channel_amplitude,
            set_channel_wavelength_amplitude,
            set_multipeaks_config,
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
        self.log_signal.emit(
            "NKT laser ready — RF stays ON during Test Data; "
            "only amplitude is stepped (no RF off/on per point)."
        )

        first_wl = step_items[0]["center_wl"] if step_items else 600.0
        pm = create_power_meter(
            cfg.get("test_pm_backend", "pm100d"),
            visa_resource=cfg.get("test_pm_visa_resource", ""),
            sim_max_w=float(cfg.get("test_pm_sim_max_w", 1.0)),
            wavelength_nm=first_wl,
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

        # ── OSA (optional) ────────────────────────────────────────────────
        osa_sock = None
        if cfg.get("test_osa_enabled") or cfg.get("osa_enabled"):
            osa_sock = self._osa_connect(cfg)
            if osa_sock:
                self.log_signal.emit(f"OSA connected → {cfg.get('osa_host', '')}:{cfg.get('osa_port', 10001)}")

        log_path = os.path.join(out_dir, cfg.get("test_log_csv", "test_data_log.csv"))
        log_exists = os.path.isfile(log_path)
        log_fields = [
            "timestamp", "step", "repeat", "wavelength_nm", "target_dbm",
            "pm_reading_W", "coupling_eff", "actual_W", "actual_dbm",
            "rf_amplitude", "exposure_ms", "gain", "filename", "status",
        ]

        total_steps = len(step_items) * len(targets_dbm)
        step_n = 0
        rows = []

        active_wl = step_items[0]["center_wl"] if step_items else 600.0

        def _set_rf_amp(amp: int):
            if isinstance(pm, SimulatedPowerMeter):
                pm.set_rf_hint(amp)
            nt.call(set_channel_amplitude, com, rf, int(amp), 0)

        def _setup_wavelength(wl_nm: float, amp: int):
            nonlocal active_wl
            active_wl = wl_nm
            if isinstance(pm, SimulatedPowerMeter):
                pm.set_rf_hint(amp)
            nt.call(
                set_channel_wavelength_amplitude,
                com, rf, wl_nm, int(amp), 0,
            )

        try:
            with open(log_path, "a", newline="", encoding="utf-8") as log_f:
                writer = csv.DictWriter(log_f, fieldnames=log_fields)
                if not log_exists:
                    writer.writeheader()

                for step_item in step_items:
                    wl = step_item["center_wl"]
                    multi_cfg = step_item["multi_cfg"]

                    if self._stop_flag.is_set():
                        self.warn_signal.emit("Stop requested.")
                        raise _AcqAbort

                    # Set PM100D correction wavelength
                    if isinstance(pm, PM100DPowerMeter):
                        try:
                            pm.set_wavelength(wl)
                            wl_label = (
                                f"{wl:.1f} nm (center)" if multi_cfg else f"{wl:.1f} nm"
                            )
                            self.log_signal.emit(f"  PM wavelength → {wl_label}")
                        except Exception as e:
                            self.warn_signal.emit(f"  PM wavelength set failed: {e}")

                    if multi_cfg is not None:
                        wls = multi_cfg["wavelengths"]
                        step_amps = multi_cfg["amplitudes"]
                        self.log_signal.emit(
                            f"══ NKT multi-peak ══ {len(wls)}ch: "
                            f"{[f'{w}nm' for w in wls]}  center={wl:.1f} nm ══"
                        )
                        nt.call(set_multipeaks_config, com, extreme, rf, emission, wls, step_amps)
                    else:
                        self.log_signal.emit(f"══ Wavelength {wl:.3f} nm ══")
                        _setup_wavelength(wl, min_amp)
                    time.sleep(laser_settle)

                    # Label/filename tag and OSA channel lists for this step
                    wl_tag = (
                        f"cwl{wl:.1f}nm" if multi_cfg is not None else f"wl{wl:.3f}nm"
                    )
                    osa_wls = multi_cfg["wavelengths"] if multi_cfg is not None else [wl]

                    osa_done_for_wl = False
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
                        self.pm_trace_reset_signal.emit(target_dbm, tol_db)
                        trace_rows = []
                        _set_rf_amp(min_amp)
                        time.sleep(min(laser_settle, 0.3))

                        def _pm_cb(t_sec, amp, pm_w, act_w, act_dbm, phase):
                            trace_rows.append({
                                "t_sec": round(t_sec, 4),
                                "rf_amplitude": amp,
                                "pm_W": pm_w,
                                "actual_W": act_w,
                                "actual_dbm": act_dbm,
                                "phase": phase,
                            })
                            self.pm_reading_signal.emit(
                                t_sec, amp, pm_w, act_w, act_dbm,
                                target_dbm, phase,
                            )

                        rf_algo = cfg.get("test_rf_algo", "ramp")
                        _servo_kwargs = dict(
                            target_dbm=target_dbm,
                            coupling_efficiency=coupling,
                            min_amp=min_amp,
                            max_amp=max_amp,
                            tolerance_db=tol_db,
                            step_interval_ms=step_interval_ms,
                            settle_s=laser_settle,
                            pm_sample_s=pm_settle,
                            verify_count=3,
                            stop_check=lambda: self._stop_flag.is_set(),
                            pm_callback=_pm_cb,
                        )
                        try:
                            if rf_algo == "bisect":
                                result = servo_rf_to_target_bisect(
                                    pm.read_power_watts,
                                    _set_rf_amp,
                                    **_servo_kwargs,
                                )
                            else:
                                result = servo_rf_to_target(
                                    pm.read_power_watts,
                                    _set_rf_amp,
                                    **_servo_kwargs,
                                )
                        except RFPowerControlError as exc:
                            msg = str(exc)
                            if "Stop requested" in msg:
                                raise _AcqAbort
                            self.warn_signal.emit(
                                f"  Step {step_n} power servo failed — capturing anyway "
                                f"(λ={wl:.1f} nm, target={target_dbm:.2f} dBm): {msg}"
                            )
                            self._save_pm_trace(
                                trace_rows, out_dir, wl, target_dbm, step_n
                            )

                            # Best-effort: last known RF amp and a fresh PM reading
                            last_rf_amp = (
                                trace_rows[-1]["rf_amplitude"] if trace_rows else min_amp
                            )
                            try:
                                pm_w_now = float(pm.read_power_watts())
                            except Exception:
                                pm_w_now = (
                                    trace_rows[-1]["pm_W"]
                                    if trace_rows
                                    else float("nan")
                                )
                            from core.power_math import actual_watts_from_pm, watts_to_dbm
                            act_w_now = (
                                actual_watts_from_pm(pm_w_now, coupling)
                                if math.isfinite(pm_w_now)
                                else float("nan")
                            )
                            act_dbm_now = (
                                watts_to_dbm(act_w_now)
                                if math.isfinite(act_w_now)
                                else float("nan")
                            )

                            # Try to capture camera frame at best-effort power
                            camera.exposure_time_us = int(exp_ms * 1000)
                            camera.issue_software_trigger()
                            frame = camera.get_pending_frame_or_null()
                            if frame is None:
                                self.warn_signal.emit(
                                    f"  Camera timeout (settle_failed) λ={wl} "
                                    f"target={target_dbm} dBm — no frame saved"
                                )
                                skip_row = {
                                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                                    "step": step_n,
                                    "repeat": 1,
                                    "wavelength_nm": wl,
                                    "target_dbm": target_dbm,
                                    "pm_reading_W": pm_w_now,
                                    "coupling_eff": coupling,
                                    "actual_W": act_w_now,
                                    "actual_dbm": act_dbm_now,
                                    "rf_amplitude": last_rf_amp,
                                    "exposure_ms": exp_ms,
                                    "gain": gain,
                                    "filename": "",
                                    "status": "settle_failed",
                                }
                                writer.writerow(skip_row)
                                log_f.flush()
                                rows.append(skip_row)
                                continue

                            buf = frame_to_image(frame.image_buffer, camera_roi)
                            safe = (
                                f"{prefix}_{wl_tag}_tgt{target_dbm:.2f}dbm"
                                f"_rf{last_rf_amp}_settle_failed.{img_fmt}"
                            )
                            path = os.path.join(out_dir, safe)
                            self._save_frame(buf, path, img_fmt)
                            self._maybe_auto_roi_crop(buf, path, out_dir, cfg)
                            self.log_signal.emit(
                                f"  Saved (settle_failed) {os.path.basename(path)}  "
                                f"actual={act_dbm_now:.2f} dBm"
                            )

                            info = (
                                f"TEST(settle_failed)  λ={wl:.1f}nm  "
                                f"tgt={target_dbm:.1f}dBm  "
                                f"act={act_dbm_now:.1f}dBm  RF={last_rf_amp}"
                            )
                            self.camera_frame_signal.emit(buf, info)
                            time.sleep(cfg.get("camera_sleep_s", 0.1))

                            if osa_sock is not None and not osa_done_for_wl:
                                osa_data, osa_sock = self._osa_measure_with_retry(
                                    osa_sock, cfg, step_n, wl,
                                    osa_wls, [last_rf_amp], out_dir
                                )
                                if osa_data is not None:
                                    osa_done_for_wl = True

                            sf_row = {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "step": step_n,
                                "repeat": 1,
                                "wavelength_nm": wl,
                                "target_dbm": target_dbm,
                                "pm_reading_W": pm_w_now,
                                "coupling_eff": coupling,
                                "actual_W": act_w_now,
                                "actual_dbm": act_dbm_now,
                                "rf_amplitude": last_rf_amp,
                                "exposure_ms": exp_ms,
                                "gain": gain,
                                "filename": os.path.basename(path),
                                "status": "settle_failed_captured",
                            }
                            writer.writerow(sf_row)
                            log_f.flush()
                            rows.append(sf_row)
                            continue

                        trig = (
                            "Crossed upper band — capture at this power"
                            if result.overshoot_trigger
                            else "In tolerance"
                        )
                        self.log_signal.emit(
                            f"  Triggered ({trig}) @ RF={result.rf_amplitude}/1000  "
                            f"PM={result.pm_reading_w:.3e} W  "
                            f"actual={result.actual_dbm:.2f} dBm  "
                            f"({result.iterations} samples)"
                        )
                        if result.status == "bracket_overflow_low":
                            self.warn_signal.emit(
                                f"⚠ RF bracket overflow: max RF={max_amp} still below "
                                f"target {target_dbm:.2f} dBm "
                                f"(achieved {result.actual_dbm:.2f} dBm) — "
                                "captured at best effort, mark for retest"
                            )
                        elif result.status == "bracket_overflow_high":
                            self.warn_signal.emit(
                                f"⚠ RF bracket overflow: min RF={min_amp} still above "
                                f"target {target_dbm:.2f} dBm "
                                f"(achieved {result.actual_dbm:.2f} dBm) — "
                                "captured at best effort, mark for retest"
                            )
                        self._save_pm_trace(
                            trace_rows, out_dir, wl, target_dbm, step_n,
                        )

                        camera.exposure_time_us = int(exp_ms * 1000)
                        for rep_idx in range(1, n_repeats + 1):
                            if self._stop_flag.is_set():
                                raise _AcqAbort
                            camera.issue_software_trigger()
                            frame = camera.get_pending_frame_or_null()
                            if frame is None:
                                self.error_signal.emit(
                                    f"Camera timeout at λ={wl} target={target_dbm} dBm"
                                    + (f" rep={rep_idx}" if n_repeats > 1 else "")
                                )
                                raise _AcqAbort

                            buf = frame_to_image(frame.image_buffer, camera_roi)
                            rep_tag = f"_rep{rep_idx}" if n_repeats > 1 else ""
                            safe = (
                                f"{prefix}_{wl_tag}_tgt{target_dbm:.2f}dbm"
                                f"_rf{result.rf_amplitude}{rep_tag}.{img_fmt}"
                            )
                            path = os.path.join(out_dir, safe)
                            self._save_frame(buf, path, img_fmt)
                            self._maybe_auto_roi_crop(buf, path, out_dir, cfg)
                            rep_info = (
                                f"  (rep {rep_idx}/{n_repeats})" if n_repeats > 1 else ""
                            )
                            self.log_signal.emit(
                                f"  Saved {os.path.basename(path)}{rep_info}"
                            )

                            info = (
                                f"TEST  λ={wl:.1f}nm  tgt={target_dbm:.1f}dBm  "
                                f"act={result.actual_dbm:.1f}dBm  RF={result.rf_amplitude}"
                                + (f"  rep={rep_idx}/{n_repeats}" if n_repeats > 1 else "")
                            )
                            self.camera_frame_signal.emit(buf, info)
                            time.sleep(cfg.get("camera_sleep_s", 0.1))

                            row = {
                                "timestamp": datetime.now().isoformat(timespec="seconds"),
                                "step": step_n,
                                "repeat": rep_idx,
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
                                "status": result.status,
                            }
                            writer.writerow(row)
                            log_f.flush()
                            rows.append(row)

                        # ── OSA measurement (optional, once per wavelength/step) ──
                        osa_data = None
                        if osa_sock is not None and not osa_done_for_wl:
                            osa_data, osa_sock = self._osa_measure_with_retry(
                                osa_sock, cfg, step_n, wl,
                                osa_wls, [result.rf_amplitude], out_dir
                            )
                            if osa_data is not None:
                                osa_done_for_wl = True

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
            if osa_sock is not None:
                try:
                    osa_sock.close()
                except Exception:
                    pass
            pm.close()
            self._nkt_shutdown(nt, com, extreme, rf)

        self.log_signal.emit(
            f"Test data collection complete — {len(rows)} frames, log → {log_path}"
        )

    @staticmethod
    def _save_pm_trace(rows, out_dir, wl_nm, target_dbm, step_n):
        if not rows:
            return
        try:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(
                out_dir,
                f"pm_trace_step{step_n}_wl{wl_nm:.3f}nm_tgt{target_dbm:.2f}dbm.csv",
            )
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=[
                        "t_sec", "rf_amplitude", "pm_W",
                        "actual_W", "actual_dbm", "phase",
                    ],
                )
                writer.writeheader()
                writer.writerows(rows)
        except Exception:
            pass

    # ── OSA helpers ────────────────────────────────────────────────────────

    def _osa_connect(self, cfg):
        host = cfg.get("osa_host", "").strip()
        port = int(cfg.get("osa_port", 10001))
        if not host:
            self.warn_signal.emit("OSA: host IP is empty — check OSA tab.")
            return None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(5)
            s.connect((host, port))
            s.settimeout(None)
            s.send(b'open "anonymous"\r\n'); time.sleep(0.2)
            s.send(b' \r\n'); time.sleep(0.2)
            return s
        except Exception as e:
            self.warn_signal.emit(f"OSA connect failed ({host}:{port}): {e}")
            return None

    def _osa_measure(self, sock, cfg, step_n, wl, wls, amps, out_dir):
        def _send(msg):
            sock.send((msg + "\r\n").encode())
            time.sleep(0.05)

        def _query(msg, timeout=15.0):
            sock.send((msg + "\r\n").encode())
            sock.settimeout(2.0)
            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                except socket.timeout:
                    if buf:
                        break
                    continue
                except Exception:
                    break
            sock.settimeout(None)
            return buf.decode("utf-8", errors="ignore").strip()

        def _wait_sweep(timeout_s=180):
            deadline = time.time() + timeout_s
            while time.time() < deadline:
                sock.send(b":stat:oper:even?\r\n")
                try:
                    sock.settimeout(3)
                    resp = sock.recv(256).decode().strip()
                    sock.settimeout(None)
                except Exception:
                    resp = "0"
                if resp and resp[0] == "1":
                    return True
                time.sleep(0.3)
            return False

        def _parse_trace(raw):
            parts = raw.split(",")
            values = []
            for p in parts:
                p = p.strip()
                try:
                    values.append(float(p))
                except ValueError:
                    continue
            return np.array(values) if values else np.array([0.0])

        try:
            _send("*RST"); time.sleep(0.3)
            _send("CFORM1")
            _send(f":sens:wav:star {cfg['osa_wl_start']}nm")
            _send(f":sens:wav:stop {cfg['osa_wl_stop']}nm")
            _send(f":sens:band:res {cfg['osa_resolution']}nm")
            _send(f":sens:sens {cfg['osa_sensitivity']}")
            _send(f":sens:sett:smo {cfg['osa_smoothing']}")
            _send(":sens:sweep:points:auto off")
            _send(f":sens:sweep:step {cfg['osa_sampling']}nm")
            _send(":sens:corr:rvel:med air")
            _send(f":sens:aver:coun {cfg['osa_avg']}")
            _send(":sens:chop OFF")
            _send(":DISPLAY:TRACE:Y1:SPACING LIN")
            _send(f":DISPLAY:TRACE:Y1:RLEVEL {cfg['osa_rlevel_nw']}nW")
            _send(":init:smode 1")
            _send("*CLS")
            _send(":init")

            if not _wait_sweep(60):
                self.warn_signal.emit(f"OSA sweep timed out at step {step_n}")
                return None

            raw_x = _query(":TRAC:DATA:X? TRA", timeout=15)
            raw_y = _query(":TRAC:DATA:Y? TRA", timeout=15)
            x_m = _parse_trace(raw_x)
            y_w = _parse_trace(raw_y)
            n = min(len(x_m), len(y_w))
            x_m = x_m[:n]
            y_w = y_w[:n]
            x_nm = x_m * 1e9
            y_nw = y_w * 1e9

            if len(x_nm) < 2:
                return None

            peak_idx = int(np.argmax(y_nw))
            self.log_signal.emit(
                f"  OSA peak: {x_nm[peak_idx]:.3f} nm  |  {y_nw[peak_idx]:.1f} nW"
            )

            osa_info  = f"Peak: {x_nm[peak_idx]:.3f} nm  |  {y_nw[peak_idx]:.1f} nW"
            osa_title = f"step={step_n}  λ={wl:.1f} nm"
            self.osa_spectrum_signal.emit(x_nm, y_nw, osa_info, osa_title)

            osa_dir = out_dir
            osa_prefix = cfg.get("osa_prefix", "osa")
            if cfg.get("osa_save_png", True):
                self._osa_save_plot(x_nm, y_nw, step_n, wl, wls, amps, osa_dir, osa_prefix)
            if cfg.get("osa_save_csv", True):
                self._osa_save_csv(x_nm, y_nw, step_n, wl, wls, amps, osa_dir, osa_prefix)

            return {
                "peakX_nm": round(float(x_nm[peak_idx]), 4),
                "peakY_nW": round(float(y_nw[peak_idx]), 4),
            }
        except OSError:
            raise  # let _osa_measure_with_retry handle socket reconnection
        except Exception as e:
            self.warn_signal.emit(f"  OSA measure error: {e}")
            return None

    def _osa_measure_with_retry(self, sock, cfg, step_n, wl, wls, amps, out_dir,
                                max_retries=3):
        """Wrap _osa_measure with reconnect logic on socket errors.

        Returns (osa_data, sock) where sock may be a freshly reconnected socket
        or None if all reconnect attempts failed.
        """
        for attempt in range(max_retries + 1):
            try:
                data = self._osa_measure(sock, cfg, step_n, wl, wls, amps, out_dir)
                return data, sock
            except OSError as e:
                if attempt >= max_retries:
                    self.warn_signal.emit(
                        f"  OSA: all {max_retries} reconnect attempts failed: {e}"
                    )
                    return None, None
                self.warn_signal.emit(
                    f"  OSA socket error (attempt {attempt + 1}/{max_retries}): {e}"
                    f" — reconnecting in 2 s…"
                )
                try:
                    sock.close()
                except Exception:
                    pass
                time.sleep(2)
                sock = self._osa_connect(cfg)
                if sock is None:
                    self.warn_signal.emit("  OSA reconnect failed — giving up.")
                    return None, None
        return None, sock

    @staticmethod
    def _osa_save_csv(x_nm, y_nw, step_n, wl, wls, amps, out_dir, prefix="osa"):
        try:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{prefix}_step{step_n}.csv")
            with open(path, "w", newline="") as f:
                f.write(f"# step={step_n}  λ={wl}nm  wavelengths={wls}  amplitudes={amps}\n")
                f.write("wavelength_nm,power_nw\n")
                for x, y in zip(x_nm, y_nw):
                    f.write(f"{x:.6f},{y:.6f}\n")
        except Exception:
            pass

    @staticmethod
    def _osa_save_plot(x_nm, y_nw, step_n, wl, wls, amps, out_dir, prefix="osa"):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            os.makedirs(out_dir, exist_ok=True)
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(x_nm, y_nw, color="steelblue", linewidth=0.8)
            for w in wls:
                ax.axvline(w, color="tomato", alpha=0.5, linestyle="--", linewidth=0.8)
            peak_idx = int(np.argmax(y_nw))
            ax.plot(x_nm[peak_idx], y_nw[peak_idx], "r^", markersize=6,
                    label=f"peak={x_nm[peak_idx]:.3f} nm")
            ax.set_xlabel("Wavelength (nm)")
            ax.set_ylabel("Power (nW)")
            ax.set_title(f"OSA step={step_n}  λ={wl:.1f} nm")
            ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
            fig.tight_layout()
            path = os.path.join(out_dir, f"{prefix}_step{step_n}.png")
            fig.savefig(path, dpi=120, bbox_inches="tight")
            plt.close(fig)
        except Exception:
            pass

    def _maybe_auto_roi_crop(self, buf, img_path: str, out_dir: str, cfg: dict):
        """Run ROI crop post-process if enabled in config (mirrors LoopRunner)."""
        from core.roi_postprocess import (
            RoiPostprocessError,
            postprocess_config_from_cfg,
            postprocess_frame,
        )
        settings = postprocess_config_from_cfg(cfg)
        if not settings:
            return
        try:
            result = postprocess_frame(buf, img_path, out_dir=out_dir, settings=settings)
            cropped = result["cropped"]
            if result.get("tif"):
                self.log_signal.emit(
                    f"  Cropped → {settings.get('subdir', 'cropped')}/"
                    f"{os.path.basename(result['tif'])}"
                )
            if cfg.get("auto_roi_show_preview", True):
                ch, cw = cropped.shape
                self.camera_frame_signal.emit(
                    cropped,
                    f"CROPPED  {cw}×{ch}  {os.path.basename(img_path)}",
                )
        except RoiPostprocessError as exc:
            self.warn_signal.emit(f"  Auto ROI crop failed: {exc}")
        except Exception as exc:
            self.warn_signal.emit(f"  Auto ROI crop error: {exc}")

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

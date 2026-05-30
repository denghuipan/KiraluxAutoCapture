"""
LoopRunner — QThread that executes the full acquisition loop.

Camera and NKT laser are REQUIRED. If either is unavailable the loop
aborts with a clear error before starting any acquisition.
OSA is optional — if not connected the loop continues without it.

All NKT DLL calls are dispatched via nkt_thread.call() so they execute
in the dedicated NKT thread (avoids Qt IBHandler cross-thread errors).
"""
import os
import sys
import time
import json
import socket
import csv
import threading

import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


def _try_import_camera():
    try:
        from thorlabs_tsi_sdk.tl_camera import TLCameraSDK
        return TLCameraSDK
    except Exception:
        return None


class _AcqAbort(BaseException):
    pass


class LoopRunner(QThread):
    log_signal          = pyqtSignal(str)
    warn_signal         = pyqtSignal(str)
    error_signal        = pyqtSignal(str)
    progress_signal     = pyqtSignal(int, str)
    finished_signal     = pyqtSignal(bool)
    osa_spectrum_signal = pyqtSignal(np.ndarray, np.ndarray, str, str)
    camera_frame_signal = pyqtSignal(np.ndarray, str)

    def __init__(self, cfg: dict, nkt_thread=None):
        super().__init__()
        self.cfg = cfg
        self.nkt_thread = nkt_thread
        self._stop_flag = threading.Event()
        self._img_h5_writer = None
        self._osa_h5_writer = None
        self._base_out_dir = "."

    def request_stop(self):
        self._stop_flag.set()

    def run(self):
        try:
            self._main()
        except _AcqAbort:
            pass
        except BaseException as e:
            self.error_signal.emit(f"Unhandled exception: {e}")
            self.finished_signal.emit(False)
        finally:
            self._close_h5_writers()

    def _close_h5_writers(self):
        if self._img_h5_writer:
            n = self._img_h5_writer.count
            path = self._img_h5_writer.path
            self._img_h5_writer.close()
            self._img_h5_writer = None
            if n:
                self.log_signal.emit(f"Image H5 closed — {n} samples in {path}")
        if self._osa_h5_writer:
            n = self._osa_h5_writer.count
            path = self._osa_h5_writer.path
            self._osa_h5_writer.close()
            self._osa_h5_writer = None
            if n:
                self.log_signal.emit(f"OSA H5 closed — {n} samples in {path}")

    def _main(self):
        cfg = self.cfg
        osa_only   = cfg.get("osa_only", False)
        out_dir    = cfg.get("out_dir", ".")
        prefix     = cfg.get("file_prefix", "img_loop")
        comport    = cfg.get("comport", "COM5")
        crystal    = cfg.get("crystal_num", 0)
        emission   = cfg.get("emission_percent", 100)
        exp_ms     = cfg.get("exposure_time_ms", 0.06)
        gain       = cfg.get("gain", 0)
        timeout_ms = cfg.get("timeout_ms", 5000)

        os.makedirs(out_dir, exist_ok=True)

        self._base_out_dir = os.path.abspath(out_dir)
        from core.h5_store import open_image_h5_writer, open_osa_h5_writer

        self._img_h5_writer = open_image_h5_writer(cfg, self._base_out_dir)
        self._osa_h5_writer = open_osa_h5_writer(cfg, self._base_out_dir)
        if self._img_h5_writer:
            self.log_signal.emit(
                f"Image H5 ON → {self._img_h5_writer.path}  "
                f"(labels: roundXX_loopYY_j)"
            )
        if self._osa_h5_writer:
            renamed = getattr(self._osa_h5_writer, "_renamed_from", None)
            if renamed:
                self.warn_signal.emit(
                    f"OSA H5: existing file had wrong spectrum size — "
                    f"renamed to {os.path.basename(renamed)}; starting fresh."
                )
            self.log_signal.emit(
                f"OSA H5 ON → {self._osa_h5_writer.path}  "
                f"(reduce to {cfg.get('osa_reduce_points', 300)} pts)"
            )

        from core.roi_postprocess import postprocess_config_from_cfg
        auto_roi_settings = postprocess_config_from_cfg(cfg)
        if auto_roi_settings:
            sub = auto_roi_settings.get("subdir", "cropped")
            self.log_signal.emit(
                f"Auto ROI crop ON → {sub}/  "
                f"signal {auto_roi_settings['signal_width']}×{auto_roi_settings['signal_height']}  "
                f"outer {auto_roi_settings['outer_width']}×{auto_roi_settings['outer_height']}"
            )

        if cfg.get("training_enabled"):
            rounds = cfg.get("training_rounds", [])
            n_rounds = cfg.get("training_n_rounds", 0)
            if len(rounds) != n_rounds:
                self.error_signal.emit(
                    f"Training strategy incomplete — saved {len(rounds)}/{n_rounds} rounds."
                )
                self.finished_signal.emit(False)
                return
            pass_cfgs = []
            base_osa_dir = cfg.get("osa_save_dir", cfg.get("out_dir", "."))
            for ri, rc in enumerate(rounds, 1):
                merged = dict(cfg)
                merged.update(rc)
                round_dir = os.path.join(out_dir, f"round_{ri}")
                merged["out_dir"] = round_dir
                merged["file_prefix"] = f"{prefix}_r{ri}"
                merged["osa_save_dir"] = os.path.join(base_osa_dir, f"round_{ri}")
                merged["training_round_index"] = ri
                pass_cfgs.append(merged)
            total_captures = sum(
                p.get("n_steps", 0) * p.get("n_repeats", 1) for p in pass_cfgs
            )
        else:
            pass_cfgs = [cfg]
            total_captures = cfg.get("n_steps", 10) * cfg.get("n_repeats", 1)

        TLCameraSDK = None
        extreme = RF_power = SuperK_sel = None
        sdk = camera = None
        camera_ok = False
        camera_roi = (0, 0, 4096, 2160)
        nt = self.nkt_thread

        # ── NKT init via dedicated thread ─────────────────────────────────
        if nt is None:
            self.error_signal.emit("NKT thread not available — cannot start acquisition.")
            self.finished_signal.emit(False)
            raise _AcqAbort

        try:
            extreme, RF_power, SuperK_sel, nkt_comport = self._nkt_init(comport)
        except Exception as e:
            self.error_signal.emit(f"NKT scan failed: {e}")
            self.finished_signal.emit(False)
            raise _AcqAbort

        if extreme is None or not nkt_comport:
            self.error_signal.emit(
                "No NKT device found — cannot start acquisition.\n"
                "Use Hardware Test → Scan all NKT ports, check USB, and close other NKT software."
            )
            self.finished_signal.emit(False)
            raise _AcqAbort

        comport = nkt_comport

        try:
            self._nkt_startup(comport, extreme, RF_power, SuperK_sel, crystal, emission)
        except Exception as e:
            self.warn_signal.emit(f"NKT startup error: {e}")

        # ── Camera ────────────────────────────────────────────────────────
        if not osa_only:
            TLCameraSDK = _try_import_camera()
            if TLCameraSDK is None:
                self.error_signal.emit(
                    "Thorlabs SDK not found — cannot start acquisition."
                )
                self._nkt_shutdown(comport, extreme, RF_power)
                self.finished_signal.emit(False)
                raise _AcqAbort
            try:
                from core.camera_support import set_camera_roi, frame_to_image

                sdk = TLCameraSDK()
                cams = sdk.discover_available_cameras()
                if not cams:
                    self.error_signal.emit("No Kiralux camera detected.")
                    self._nkt_shutdown(comport, extreme, RF_power)
                    self.finished_signal.emit(False)
                    raise _AcqAbort
                camera = sdk.open_camera(cams[0])
                roi_requested = cfg.get("roi", (0, 0, 4096, 2160))
                camera_roi = set_camera_roi(camera, roi_requested)
                camera.exposure_time_us = int(exp_ms * 1000)
                camera.frames_per_trigger_zero_for_unlimited = 0
                camera.image_poll_timeout_ms = int(timeout_ms)
                camera.gain = int(gain)
                camera.arm(2)
                camera_ok = True
                w_roi = camera_roi[2] - camera_roi[0]
                h_roi = camera_roi[3] - camera_roi[1]
                self.log_signal.emit(
                    f"Camera ready  (exp={exp_ms} ms, gain={gain}, "
                    f"ROI={camera_roi}  {w_roi}x{h_roi})"
                )
            except Exception as e:
                self.error_signal.emit(f"Camera init failed: {e}")
                self._nkt_shutdown(comport, extreme, RF_power)
                self.finished_signal.emit(False)
                raise _AcqAbort
        else:
            self.log_signal.emit("Only OSA mode — Camera skipped.")

        # ── OSA ───────────────────────────────────────────────────────────
        osa_sock = None
        if cfg.get("osa_enabled"):
            osa_sock = self._osa_connect(cfg)
            if osa_only and osa_sock is None:
                self.error_signal.emit("Only OSA mode: OSA connection failed.")
                self.finished_signal.emit(False)
                raise _AcqAbort

        all_osa_rows = []
        done = 0

        for pi, pass_cfg in enumerate(pass_cfgs):
            if self._stop_flag.is_set():
                break
            round_idx = pass_cfg.get("training_round_index")
            if round_idx is not None:
                mode_names = {0: "Random Multi", 1: "Manual", 2: "Single Peak", 3: "Broadband"}
                mname = mode_names.get(pass_cfg.get("mode", 0), "?")
                self.log_signal.emit(
                    f"═══ Training Round {round_idx}/{len(pass_cfgs)}  "
                    f"({mname})  →  {pass_cfg['out_dir']} ═══"
                )
            done, osa_rows = self._run_pass(
                pass_cfg,
                camera=camera,
                camera_roi=camera_roi,
                camera_ok=camera_ok,
                extreme=extreme,
                RF_power=RF_power,
                emission=emission,
                comport=comport,
                osa_sock=osa_sock,
                osa_only=osa_only,
                done_offset=done,
                total_captures=total_captures,
            )
            all_osa_rows.extend(osa_rows)

            if not self._stop_flag.is_set() and pass_cfg.get("inline_test_enabled"):
                self._run_inline_test(
                    pi, pass_cfg,
                    camera=camera,
                    camera_roi=camera_roi,
                    camera_ok=camera_ok,
                    extreme=extreme,
                    RF_power=RF_power,
                    emission=emission,
                    comport=comport,
                    osa_sock=osa_sock,
                    osa_only=osa_only,
                )

        # ── Cleanup ───────────────────────────────────────────────────────
        if extreme is not None:
            try:
                self._nkt_shutdown(comport, extreme, RF_power)
            except Exception as e:
                self.warn_signal.emit(f"NKT shutdown error: {e}")

        if camera_ok:
            try:
                camera.disarm(); camera.dispose()
            except Exception:
                pass
        if sdk:
            try:
                sdk.dispose()
            except Exception:
                pass
        if osa_sock:
            try:
                osa_sock.close()
            except Exception:
                pass

        if all_osa_rows:
            osa_csv_path = os.path.join(out_dir, cfg.get("osa_filename", "osa_log.csv"))
            osa_fields = ["loop_i", "loop_j", "n_channels", "wavelengths_nm",
                          "amplitudes", "peakX_nm", "peakY_nW"]
            if cfg.get("training_enabled"):
                osa_fields = ["training_round"] + osa_fields
                for row in all_osa_rows:
                    row.setdefault("training_round", row.get("training_round", ""))
            try:
                with open(osa_csv_path, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=osa_fields)
                    writer.writeheader()
                    writer.writerows(all_osa_rows)
                self.log_signal.emit(f"OSA log saved → {osa_csv_path}")
            except Exception as e:
                self.warn_signal.emit(f"OSA CSV save failed: {e}")

        self.log_signal.emit(f"Loop complete — {done}/{total_captures} captures done.")
        self.finished_signal.emit(True)

    def _run_pass(
        self,
        cfg,
        *,
        camera,
        camera_roi,
        camera_ok,
        extreme,
        RF_power,
        emission,
        comport,
        osa_sock,
        osa_only,
        done_offset,
        total_captures,
    ):
        """Execute one capture pass (single mode or one training round)."""
        from core.camera_support import frame_to_image

        mode       = cfg.get("mode", 0)
        n_steps    = cfg.get("n_steps", 10)
        n_repeats  = cfg.get("n_repeats", 1)
        start_idx  = cfg.get("start_index", 1)
        settle_s   = cfg.get("laser_settle_s", 0.5)
        out_dir    = cfg.get("out_dir", ".")
        prefix     = cfg.get("file_prefix", "img_loop")
        round_idx  = cfg.get("training_round_index")

        os.makedirs(out_dir, exist_ok=True)

        configs = self._build_configs(cfg, mode, n_steps)
        if not configs:
            self.error_signal.emit("No valid configs — check wavelength range / manual table.")
            return done_offset, []

        self._export_config_csv(cfg, mode, configs, out_dir)

        osa_rows = []
        done = done_offset

        for i, step_cfg in enumerate(configs):
            if self._stop_flag.is_set():
                self.warn_signal.emit("Stop requested — exiting loop.")
                break

            wls  = step_cfg["wavelengths"]
            amps = step_cfg["amplitudes"]
            loop_i = i + start_idx

            _step_label = step_cfg.get("label")
            if _step_label:
                self.log_signal.emit(
                    f"Step {loop_i}  ({i+1}/{n_steps})  |  {_step_label}"
                )
            else:
                self.log_signal.emit(
                    f"Step {loop_i}  ({i+1}/{n_steps})  |  "
                    f"{len(wls)}ch: {[f'{w}nm' for w in wls]}"
                )

            _step_emission = step_cfg.get("emission", emission)
            if extreme is not None:
                try:
                    self._nkt_set_multipeaks(
                        comport, extreme, RF_power, _step_emission,
                        wls, amps,
                    )
                    time.sleep(settle_s)
                except Exception as e:
                    self.warn_signal.emit(f"NKT set failed at step {loop_i}: {e}")

            for j in range(1, n_repeats + 1):
                if self._stop_flag.is_set():
                    break

                if not osa_only:
                    img_fmt  = cfg.get("img_format", "tif")
                    img_name = os.path.join(out_dir, f"{prefix}{loop_i}_{j}.{img_fmt}")
                    try:
                        camera.issue_software_trigger()
                        frame = camera.get_pending_frame_or_null()
                        if frame is not None:
                            buf = frame_to_image(frame.image_buffer, camera_roi)
                            h, w = buf.shape
                            self._save_frame(buf, img_name, img_fmt)
                            self.log_signal.emit(f"  Saved {os.path.basename(img_name)}")
                            info = f"i={loop_i} j={j}  |  {w}×{h}  max={buf.max()}"
                            self.camera_frame_signal.emit(buf, info)
                            self._maybe_auto_roi_crop(
                                buf, img_name, out_dir, cfg,
                                loop_i=loop_i, loop_j=j,
                            )
                            time.sleep(cfg.get("camera_sleep_s", 0.1))
                        else:
                            self.error_signal.emit(
                                f"  Camera timeout at i={loop_i} j={j} — stopping."
                            )
                            self._stop_flag.set()
                            break
                    except Exception as e:
                        self.error_signal.emit(
                            f"  Camera error at i={loop_i} j={j}: {e} — stopping."
                        )
                        self._stop_flag.set()
                        break

                if osa_sock is not None:
                    row = self._osa_measure(osa_sock, cfg, loop_i, j, wls, amps, out_dir)
                    if row:
                        if round_idx is not None:
                            row["training_round"] = round_idx
                        osa_rows.append(row)

                done += 1
                pct = int(done / total_captures * 100) if total_captures else 0
                status = f"Step {loop_i}/{n_steps}  repeat {j}/{n_repeats}"
                if round_idx is not None:
                    status = f"Round {round_idx}  |  {status}"
                self.progress_signal.emit(pct, status)

        return done, osa_rows

    # ── Inline test-set capture ────────────────────────────────────────────
    def _run_inline_test(
        self,
        pass_idx: int,
        pass_cfg: dict,
        *,
        camera,
        camera_roi,
        camera_ok: bool,
        extreme,
        RF_power,
        emission: int,
        comport: str,
        osa_sock,
        osa_only: bool,
    ):
        """Capture one image + one OSA measurement for a random subset of the
        round's step configs, saving results to <out_dir>/test/."""
        from core.camera_support import frame_to_image

        pct        = float(pass_cfg.get("inline_test_pct", 10.0))
        seed_off   = int(pass_cfg.get("inline_test_seed_offset", 0))
        main_seed  = int(pass_cfg.get("seed", 42))
        mode       = pass_cfg.get("mode", 0)
        n_steps    = pass_cfg.get("n_steps", 10)
        start_idx  = pass_cfg.get("start_index", 1)
        settle_s   = pass_cfg.get("laser_settle_s", 0.5)
        out_dir    = pass_cfg.get("out_dir", ".")
        prefix     = pass_cfg.get("file_prefix", "img_loop")
        img_fmt    = pass_cfg.get("img_format", "tif")
        round_idx  = pass_cfg.get("training_round_index")

        test_dir = os.path.join(out_dir, "test")
        os.makedirs(test_dir, exist_ok=True)

        configs = self._build_configs(pass_cfg, mode, n_steps)
        if not configs:
            self.warn_signal.emit("[TEST] No configs available for inline test set.")
            return

        n_test = max(1, round(len(configs) * pct / 100))
        rng_seed = main_seed + pass_idx * 1000 + seed_off
        rng = np.random.default_rng(rng_seed)
        sampled_indices = sorted(
            rng.choice(len(configs), size=min(n_test, len(configs)), replace=False).tolist()
        )

        round_label = f"Round {round_idx}" if round_idx is not None else "pass"
        self.log_signal.emit(
            f"[TEST] {round_label}: sampling {len(sampled_indices)}/{len(configs)} steps "
            f"(seed={rng_seed}, pct={pct:.0f}%)  →  {test_dir}"
        )

        for idx in sampled_indices:
            if self._stop_flag.is_set():
                break

            step_cfg   = configs[idx]
            wls        = step_cfg["wavelengths"]
            amps       = step_cfg["amplitudes"]
            loop_i     = idx + start_idx
            _step_emission = step_cfg.get("emission", emission)

            _step_label = step_cfg.get("label")
            if _step_label:
                self.log_signal.emit(f"[TEST] {round_label} step {loop_i}  |  {_step_label}")
            else:
                self.log_signal.emit(
                    f"[TEST] {round_label} step {loop_i}  |  "
                    f"{len(wls)}ch: {[f'{w}nm' for w in wls]}"
                )

            if extreme is not None:
                try:
                    self._nkt_set_multipeaks(
                        comport, extreme, RF_power, _step_emission, wls, amps,
                    )
                    time.sleep(settle_s)
                except Exception as e:
                    self.warn_signal.emit(
                        f"[TEST] NKT set failed at step {loop_i}: {e}"
                    )

            if camera_ok and not osa_only:
                img_name = os.path.join(test_dir, f"{prefix}{loop_i}_1.{img_fmt}")
                try:
                    camera.issue_software_trigger()
                    frame = camera.get_pending_frame_or_null()
                    if frame is not None:
                        buf = frame_to_image(frame.image_buffer, camera_roi)
                        self._save_frame(buf, img_name, img_fmt)
                        self.log_signal.emit(
                            f"[TEST]   Saved {os.path.basename(img_name)}"
                        )
                        h, w = buf.shape
                        self.camera_frame_signal.emit(
                            buf, f"[TEST] i={loop_i}  {w}×{h}  max={buf.max()}"
                        )
                    else:
                        self.warn_signal.emit(
                            f"[TEST] Camera timeout at step {loop_i}"
                        )
                except Exception as e:
                    self.warn_signal.emit(
                        f"[TEST] Camera error at step {loop_i}: {e}"
                    )

            if osa_sock is not None:
                test_osa_cfg = dict(pass_cfg)
                test_osa_cfg["osa_save_dir"] = test_dir
                test_osa_cfg["osa_prefix"]   = "osa"
                self._osa_measure(osa_sock, test_osa_cfg, loop_i, 1, wls, amps, test_dir)

        self.log_signal.emit(f"[TEST] {round_label}: inline test-set complete.")

    # ── Config export ──────────────────────────────────────────────────────
    def _export_config_csv(self, cfg, mode, configs, out_dir):
        """Save generated NKT configs to a CSV with descriptive filename."""
        try:
            os.makedirs(out_dir, exist_ok=True)
            if mode == 0:
                seed     = cfg.get("seed", 0)
                wl_min   = cfg.get("wl_min", 620)
                wl_max   = cfg.get("wl_max", 690)
                sp_mode  = cfg.get("spacing_mode", 0)
                ch_min   = cfg.get("n_ch_min", 2)
                ch_max   = cfg.get("n_ch_max", 8)
                amp_min  = cfg.get("amp_min", 200)
                amp_max  = cfg.get("amp_max", 1000)
                emission = cfg.get("emission_percent", 100)

                if sp_mode == 0:
                    step_v = cfg.get("wl_step", 5)
                    sp_tag = f"grid{step_v:.1f}nm"
                else:
                    s_min = cfg.get("spacing_min", 0.1)
                    s_max = cfg.get("spacing_max", 1.0)
                    sp_tag = f"rand{s_min:.1f}-{s_max:.1f}nm"

                fname = (
                    f"nkt_config_seed{seed}"
                    f"_{wl_min:.0f}-{wl_max:.0f}nm"
                    f"_{sp_tag}"
                    f"_ch{ch_min}-{ch_max}"
                    f"_amp{amp_min}-{amp_max}"
                    f"_em{emission}pct"
                    f".csv"
                )
            elif mode == 2:
                wl_min  = cfg.get("single_wl_min", 620)
                wl_max  = cfg.get("single_wl_max", 690)
                step    = cfg.get("single_step", 0.5)
                amp     = cfg.get("single_amp", 1000)
                fname = (
                    f"nkt_config_singlescan"
                    f"_{wl_min:.0f}-{wl_max:.0f}nm"
                    f"_step{step:.1f}nm"
                    f"_amp{amp}"
                    f".csv"
                )
            elif mode == 3:
                bb_wl_min = cfg.get("bb_wl_min", 620)
                bb_wl_max = cfg.get("bb_wl_max", 670)
                center_tag = "fixedcenter" if cfg.get("bb_fixed_center") else "randcenter"
                sp_tag = "autosp" if cfg.get("bb_auto_spacing") else f"sp{cfg.get('bb_spacing_nm', 1.0):.1f}nm"
                fname = (
                    f"nkt_config_broadband"
                    f"_{bb_wl_min:.0f}-{bb_wl_max:.0f}nm"
                    f"_{center_tag}"
                    f"_{sp_tag}"
                    f".csv"
                )
            else:
                fname = "nkt_config_manual.csv"

            path = os.path.join(out_dir, fname)
            with open(path, "w", newline="") as f:
                mode_str = {0: "random", 1: "manual", 2: "single", 3: "broadband"}.get(mode, "unknown")
                f.write(f"# mode={mode_str}\n")
                for key in ["seed", "n_steps", "n_repeats",
                            "wl_min", "wl_max", "spacing_mode",
                            "wl_step", "spacing_min", "spacing_max",
                            "n_ch_min", "n_ch_max",
                            "amp_min", "amp_max",
                            "emission_percent", "crystal_num",
                            "comport", "laser_settle_s"]:
                    if key in cfg:
                        f.write(f"# {key}={cfg[key]}\n")

                writer = csv.writer(f)
                writer.writerow([
                    "step", "n_channels",
                    "wavelengths_nm", "amplitudes",
                ])
                for i, sc in enumerate(configs):
                    writer.writerow([
                        i + cfg.get("start_index", 1),
                        len(sc["wavelengths"]),
                        ";".join(f"{w:.1f}" for w in sc["wavelengths"]),
                        ";".join(str(a) for a in sc["amplitudes"]),
                    ])
            self.log_signal.emit(f"Config CSV saved → {fname}")
        except Exception as e:
            self.warn_signal.emit(f"Config CSV export failed: {e}")

    # ── Config generation ─────────────────────────────────────────────────
    def _build_configs(self, cfg, mode, n_steps):
        """Delegate to the shared helper in nkt_support for consistent output."""
        from core.nkt_support import build_nkt_step_configs
        return build_nkt_step_configs(cfg)

    # ── NKT helpers (all dispatched via nkt_thread.call) ──────────────────

    def _nkt_init(self, comport_hint):
        """Discovery scan via NKT thread. Returns (extreme, rf, sk, comport)."""
        from core.nkt_support import discover_nkt_modules

        com, ex, rf, sk, err = self.nkt_thread.call(
            discover_nkt_modules, comport_hint, 0.5
        )
        if err:
            self.warn_signal.emit(err)
            return None, None, None, None
        self.log_signal.emit(f"NKT on {com}  extreme@{ex}  RF@{rf}  sel@{sk}")
        return ex, rf, sk, com

    def _nkt_startup(self, comport, extreme, RF_power, SuperK_sel,
                     crystal_num, emission_pct):
        from core.nkt_support import (
            Extreme_turnON, crystal_select, RF_turnON, nkt_safety_init,
        )

        sk = SuperK_sel if SuperK_sel is not None else -1
        self.nkt_thread.call(Extreme_turnON, comport, extreme, emission_pct)
        self.nkt_thread.call(crystal_select, comport, RF_power, sk, crystal_num)
        self.nkt_thread.call(RF_turnON, comport, RF_power)

        self.nkt_thread.call(nkt_safety_init, comport, extreme, RF_power,
                             emission_pct)
        self.log_signal.emit("NKT laser ON, RF ON, safety init done.")

    def _nkt_set_multipeaks(self, comport, extreme, RF_power,
                            emission_pct, wavelengths, amplitudes):
        from core.nkt_support import set_multipeaks_config
        self.nkt_thread.call(
            set_multipeaks_config, comport, extreme, RF_power,
            emission_pct, wavelengths, amplitudes,
        )

    def _nkt_shutdown(self, comport, extreme, RF_power):
        from core.nkt_support import nkt_full_shutdown
        self.nkt_thread.call(nkt_full_shutdown, comport, extreme, RF_power)
        self.log_signal.emit("NKT shutdown complete.")

    # ── OSA helpers ───────────────────────────────────────────────────────
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
            self.log_signal.emit(f"OSA connected → {host}:{port}")
            return s
        except Exception as e:
            self.warn_signal.emit(f"OSA connect failed ({host}:{port}): {e}")
            return None

    def _osa_measure(self, sock, cfg, loop_i, loop_j, wls, amps, out_dir):
        self.log_signal.emit(
            f"  OSA measure started (i={loop_i}, j={loop_j})"
        )

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
            self.log_signal.emit(f"  OSA sweep started...")
            if not _wait_sweep(60):
                self.warn_signal.emit(
                    f"OSA sweep timed out at i={loop_i} j={loop_j}")
                return None
            self.log_signal.emit(f"  OSA sweep complete, fetching trace data...")

            raw_x = _query(":TRAC:DATA:X? TRA", timeout=15)
            raw_y = _query(":TRAC:DATA:Y? TRA", timeout=15)

            x_m  = _parse_trace(raw_x)
            y_w  = _parse_trace(raw_y)
            self.log_signal.emit(f"  OSA trace parsed: X={len(x_m)}, Y={len(y_w)} points")

            n = min(len(x_m), len(y_w))
            x_m = x_m[:n]
            y_w = y_w[:n]

            x_nm = x_m * 1e9
            y_nw = y_w * 1e9

            if len(x_nm) < 2:
                self.warn_signal.emit(
                    f"OSA too few points at i={loop_i} j={loop_j}  "
                    f"(got {len(x_nm)})")
                return None

            peak_idx = int(np.argmax(y_nw))

            info  = f"Peak: {x_nm[peak_idx]:.3f} nm  |  {y_nw[peak_idx]:.1f} nW"
            title = f"i={loop_i}  j={loop_j}  |  {len(wls)}ch: {[f'{w}nm' for w in wls]}"
            self.osa_spectrum_signal.emit(x_nm, y_nw, info, title)

            osa_dir    = cfg.get("osa_save_dir", out_dir)
            osa_prefix = cfg.get("osa_prefix", "osa")
            if cfg.get("osa_save_png", True):
                self._osa_save_plot(x_nm, y_nw, loop_i, loop_j, wls, amps,
                                    osa_dir, osa_prefix)
            if cfg.get("osa_save_csv", True):
                self._osa_save_csv(x_nm, y_nw, loop_i, loop_j, wls, amps,
                                   osa_dir, osa_prefix)

            osa_fname = f"{osa_prefix}_{loop_i}_{loop_j}.csv"
            self._maybe_osa_h5_append(
                x_nm, y_nw, cfg, loop_i, loop_j, osa_fname,
            )

            return {
                "loop_i": loop_i, "loop_j": loop_j,
                "n_channels": len(wls),
                "wavelengths_nm": json.dumps(wls),
                "amplitudes": json.dumps(amps),
                "peakX_nm": round(float(x_nm[peak_idx]), 4),
                "peakY_nW": round(float(y_nw[peak_idx]), 4),
            }
        except Exception as e:
            import traceback
            self.warn_signal.emit(
                f"OSA measure error at i={loop_i} j={loop_j}: {e}\n{traceback.format_exc()}"
            )
            return None

    def _maybe_auto_roi_crop(self, buf, img_name, out_dir, cfg, *, loop_i, loop_j):
        """Optional: run notebook ROI algorithm immediately after each saved frame."""
        from core.roi_postprocess import (
            RoiPostprocessError,
            postprocess_config_from_cfg,
            postprocess_frame,
        )
        from core.sample_label import make_sample_label

        settings = postprocess_config_from_cfg(cfg)
        if not settings:
            return
        try:
            result = postprocess_frame(
                buf, img_name, out_dir=out_dir, settings=settings
            )
            cropped = result["cropped"]
            if result.get("tif"):
                tif_name = os.path.basename(result["tif"])
                self.log_signal.emit(
                    f"  Cropped → {settings.get('subdir', 'cropped')}/{tif_name}"
                )
            label = make_sample_label(
                loop_i, loop_j, round_idx=cfg.get("training_round_index"),
            )
            if self._img_h5_writer:
                from core.image_contrast import prepare_image_for_h5
                h5_image, vmin, vmax = prepare_image_for_h5(cropped, cfg)
                idx = self._img_h5_writer.append(
                    h5_image, label, os.path.basename(img_name),
                )
                extra = ""
                if cfg.get("auto_roi_h5_contrast_enabled"):
                    extra = f"  vmin={vmin:.1f} vmax={vmax:.1f}"
                self.log_signal.emit(
                    f"  Image H5 [{label}] index={idx} → "
                    f"{os.path.basename(self._img_h5_writer.path)}{extra}"
                )
            if cfg.get("auto_roi_show_preview", True):
                ch, cw = cropped.shape
                roi = result["roi"]
                info = (
                    f"CROPPED  {label}  {cw}×{ch}  sum={roi.score:.0f}  "
                    f"box=[{roi.x1},{roi.y1},{roi.width},{roi.height}]"
                )
                self.camera_frame_signal.emit(cropped, info)
        except RoiPostprocessError as exc:
            self.warn_signal.emit(f"  Auto ROI crop failed: {exc}")
        except Exception as exc:
            self.warn_signal.emit(f"  Auto ROI crop error: {exc}")

    def _maybe_osa_h5_append(
        self, x_nm, y_nw, cfg, loop_i, loop_j, filename,
    ):
        if not self._osa_h5_writer:
            return
        from core.osa_reduce import mask_wavelength_range, reduce_dim_smooth
        from core.sample_label import make_sample_label

        try:
            wl, mag = mask_wavelength_range(
                x_nm,
                y_nw,
                float(cfg.get("osa_reduce_wl_min", 610)),
                float(cfg.get("osa_reduce_wl_max", 680)),
            )
            wl_r, mag_r = reduce_dim_smooth(
                wl,
                mag,
                num_points=int(cfg.get("osa_reduce_points", 300)),
                filter_window=int(cfg.get("osa_reduce_window", 31)),
                polyorder=int(cfg.get("osa_reduce_polyorder", 3)),
            )
            label = make_sample_label(
                loop_i, loop_j, round_idx=cfg.get("training_round_index"),
            )
            idx = self._osa_h5_writer.append(mag_r, wl_r, label, filename)
            self.log_signal.emit(
                f"  OSA H5 [{label}] index={idx} → "
                f"{os.path.basename(self._osa_h5_writer.path)}"
            )
        except Exception as exc:
            self.warn_signal.emit(f"  OSA H5 append failed: {exc}")

    def _save_frame(self, buf, path, fmt):
        if fmt == "tif":
            try:
                import tifffile
                tifffile.imwrite(path, buf)
            except ImportError:
                buf.astype(np.uint16).tofile(path)
        elif fmt == "npy":
            np.save(path, buf)
        else:
            buf.astype(np.uint16).tofile(path)

    def _osa_save_csv(self, x_nm, y_nw, loop_i, loop_j, wls, amps,
                      out_dir, prefix="osa"):
        try:
            os.makedirs(out_dir, exist_ok=True)
            path = os.path.join(out_dir, f"{prefix}_{loop_i}_{loop_j}.csv")
            with open(path, "w", newline="") as f:
                f.write(f"# loop_i={loop_i}  loop_j={loop_j}\n")
                f.write(f"# wavelengths_nm={wls}  amplitudes={amps}\n")
                f.write("wavelength_nm,power_nw\n")
                for x, y in zip(x_nm, y_nw):
                    f.write(f"{x:.6f},{y:.6f}\n")
            self.log_signal.emit(f"  OSA CSV  → {os.path.basename(path)}")
        except Exception as e:
            self.warn_signal.emit(f"  OSA CSV error: {e}")

    def _osa_save_plot(self, x_nm, y_nw, loop_i, loop_j, wls, amps,
                       out_dir, prefix="osa"):
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            os.makedirs(out_dir, exist_ok=True)
            fig, ax = plt.subplots(figsize=(10, 4))
            ax.plot(x_nm, y_nw, color="steelblue", linewidth=0.8)
            for wl, amp in zip(wls, amps):
                ax.axvline(wl, color="tomato", alpha=0.5, linestyle="--", linewidth=0.8)
            peak_idx = int(np.argmax(y_nw))
            ax.plot(x_nm[peak_idx], y_nw[peak_idx], "r^", markersize=6,
                    label=f"peak={x_nm[peak_idx]:.3f} nm")
            ax.set_xlabel("Wavelength (nm)")
            ax.set_ylabel("Power (nW)")
            ax.set_title(f"OSA i={loop_i} j={loop_j}  |  {wls} nm")
            ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
            fig.tight_layout()
            path = os.path.join(out_dir, f"{prefix}_{loop_i}_{loop_j}.png")
            fig.savefig(path, dpi=120, bbox_inches="tight")
            plt.close(fig)
            self.log_signal.emit(f"  OSA plot → {os.path.basename(path)}")
        except Exception as e:
            self.warn_signal.emit(f"  OSA plot error: {e}")

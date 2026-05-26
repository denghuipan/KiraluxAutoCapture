"""
Single persistent NKT thread — ALL NKTP_DLL calls happen here.

The DLL's internal IBHandler (QObject) has Qt thread affinity.
Every registerRead / registerWrite / openPorts / etc. must execute
in the SAME thread that first loaded the DLL.  This module provides
that single thread plus a command queue.

Usage from GUI (async):
    nkt_thread.submit("scan", preferred_comport="COM3")
    # listen to nkt_thread.scan_done / scan_error signals

Usage from another thread (sync, blocking):
    nkt_thread.call(some_func, arg1, arg2)
"""
from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal


class NKTThread(QThread):
    # ── Signals (emitted back to the GUI thread) ─────────────────────────
    scan_done  = pyqtSignal(str, int, int, int)   # comport, extreme, rf, superk
    scan_error = pyqtSignal(str)

    step_done  = pyqtSignal(str)                   # success message
    step_error = pyqtSignal(str)                   # error message

    off_done   = pyqtSignal(str)
    off_error  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._q: queue.Queue = queue.Queue()
        self._alive = True

    # ── Thread body ──────────────────────────────────────────────────────
    def run(self):
        from core.nkt_support import prepare_nkt_environment
        ok, err = prepare_nkt_environment()
        self._dll_ready = False
        self._dll_import_error = err or ""
        if not ok:
            self._dll_import_error = err or "prepare_nkt_environment failed"
        else:
            try:
                import NKTP_DLL  # noqa: F401  — IBHandler created HERE
                self._dll_ready = True
            except Exception as exc:
                self._dll_import_error = str(exc)

        while self._alive:
            try:
                item = self._q.get(timeout=0.3)
            except queue.Empty:
                continue

            cmd = item[0]

            if cmd == "_quit":
                break

            elif cmd == "_call":
                func, evt, container = item[1], item[2], item[3]
                try:
                    container["result"] = func()
                except Exception as e:
                    container["error"] = e
                finally:
                    evt.set()

            elif cmd == "scan":
                self._do_scan(item[1])

            elif cmd == "step1":
                self._do_step1(item[1], item[2])

            elif cmd == "step2":
                self._do_step2(item[1], item[2])

            elif cmd == "step3":
                self._do_step3(item[1], item[2], item[3], item[4], item[5])

            elif cmd == "test_multi":
                self._do_test_multi(item[1], item[2], item[3],
                                    item[4], item[5])

            elif cmd == "off":
                self._do_off(item[1], item[2], item[3])

    # ── Public: async commands (for GUI buttons) ─────────────────────────

    def submit_scan(self, preferred_comport: str):
        self._q.put(("scan", preferred_comport))

    def submit_step1(self, comport: str, extreme: int):
        self._q.put(("step1", comport, extreme))

    def submit_step2(self, comport: str, rf_power: int):
        self._q.put(("step2", comport, rf_power))

    def submit_step3(self, comport: str, extreme: int, rf_power: int,
                     amplitude: int, wavelength_nm: float):
        self._q.put(("step3", comport, extreme, rf_power, amplitude, wavelength_nm))

    def submit_test_multi(self, comport: str, extreme: int, rf_power: int,
                          wavelengths: list, amplitudes: list):
        self._q.put(("test_multi", comport, extreme, rf_power,
                      wavelengths, amplitudes))

    def submit_off(self, comport: str, extreme: int, rf_power: int):
        self._q.put(("off", comport, extreme, rf_power))

    # ── Public: synchronous call (for LoopRunner thread) ─────────────────

    def call(self, func, *args, timeout: float = 60.0):
        """Run *func(*args)* inside this NKT thread, blocking the caller."""
        evt = threading.Event()
        container: dict = {}

        def _wrapper():
            return func(*args)

        self._q.put(("_call", _wrapper, evt, container))
        if not evt.wait(timeout):
            raise TimeoutError("NKTThread.call() timed out")
        if "error" in container:
            raise container["error"]
        return container.get("result")

    def shutdown(self):
        self._alive = False
        self._q.put(("_quit",))
        self.wait(5000)

    # ── Internal command handlers ────────────────────────────────────────

    def _do_scan(self, preferred_comport: str):
        try:
            from core.nkt_support import discover_nkt_modules
            com, ex, rf, sk, err = discover_nkt_modules(
                preferred_comport=preferred_comport,
                settle_s=0.5,
            )
            if err:
                self.scan_error.emit(err)
            else:
                self.scan_done.emit(com, ex, rf, sk if sk is not None else -1)
        except Exception as e:
            self.scan_error.emit(str(e))

    def _do_step1(self, comport: str, extreme: int):
        try:
            from core.nkt_support import Extreme_turnON
            Extreme_turnON(comport, extreme, 100)
            self.step_done.emit("Step 1 done — Extreme ON (100%).")
        except Exception as e:
            self.step_error.emit(f"Extreme_turnON failed: {e}")

    def _do_step2(self, comport: str, rf_power: int):
        try:
            from core.nkt_support import RF_turnON
            RF_turnON(comport, rf_power)
            self.step_done.emit("Step 2 done — RF ON.")
        except Exception as e:
            self.step_error.emit(f"RF_turnON failed: {e}")

    def _do_step3(self, comport: str, extreme: int, rf_power: int,
                  amplitude: int, wavelength_nm: float):
        try:
            from core.nkt_support import nkt_test_emit
            nkt_test_emit(comport, extreme, rf_power, amplitude, wavelength_nm)
            self.step_done.emit(
                f"Step 3 done — {wavelength_nm:.1f} nm @ "
                f"{amplitude / 10:.0f}% RF amp."
            )
        except Exception as e:
            self.step_error.emit(f"nkt_test_emit failed: {e}")

    def _do_test_multi(self, comport: str, extreme: int, rf_power: int,
                       wavelengths: list, amplitudes: list):
        try:
            from core.nkt_support import nkt_safety_init
            from NKTP_DLL import registerWriteU16, registerWriteU32

            nkt_safety_init(comport, extreme, rf_power, 100)

            for i in range(8):
                registerWriteU16(comport, rf_power, 0xB0 + i, 0, -1)
                time.sleep(0.05)
            for i, (wl, amp) in enumerate(zip(wavelengths, amplitudes)):
                registerWriteU32(comport, rf_power, 0x90 + i, int(wl * 1000), -1)
                time.sleep(0.05)
                registerWriteU16(comport, rf_power, 0xB0 + i, int(amp), -1)
                time.sleep(0.05)

            wl_str = ", ".join(f"{w:.0f}nm" for w in wavelengths)
            self.step_done.emit(f"Test emit OK — {len(wavelengths)} ch: {wl_str}")
        except Exception as e:
            self.step_error.emit(f"Test multi-ch emit failed: {e}")

    def _do_off(self, comport: str, extreme: int, rf_power: int):
        try:
            from core.nkt_support import nkt_full_shutdown
            nkt_full_shutdown(comport, extreme, rf_power)
            self.off_done.emit("NKT OFF — Extreme + RF disabled.")
        except Exception as e:
            self.off_error.emit(f"Shutdown failed: {e}")

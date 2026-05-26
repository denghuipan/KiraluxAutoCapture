"""
Hardware tester workers — each runs in a QThread so the GUI stays responsive.

NKT operations are handled by core.nkt_thread.NKTThread (single persistent
thread for all DLL calls).  This file only contains Camera and OSA workers.
"""
import time
import socket
import numpy as np

from PyQt5.QtCore import QThread, pyqtSignal


# ── Camera ────────────────────────────────────────────────────────────────────
class CameraTestWorker(QThread):
    """Capture a single test frame."""
    success_signal = pyqtSignal(np.ndarray)
    error_signal   = pyqtSignal(str)

    def __init__(
        self,
        exposure_ms: float = 0.06,
        gain: int = 0,
        timeout_ms: int = 5000,
        roi=(0, 0, 4096, 2160),
    ):
        super().__init__()
        self.exposure_ms = exposure_ms
        self.gain        = gain
        self.timeout_ms  = timeout_ms
        self.roi         = roi

    def run(self):
        try:
            from thorlabs_tsi_sdk.tl_camera import TLCameraSDK
        except Exception as e:
            self.error_signal.emit(f"SDK import failed: {e}")
            return
        try:
            with TLCameraSDK() as sdk:
                cams = sdk.discover_available_cameras()
                if not cams:
                    self.error_signal.emit("No cameras detected.")
                    return
                from core.camera_support import set_camera_roi, frame_to_image

                with sdk.open_camera(cams[0]) as cam:
                    camera_roi = set_camera_roi(cam, self.roi)
                    cam.exposure_time_us               = int(self.exposure_ms * 1000)
                    cam.frames_per_trigger_zero_for_unlimited = 0
                    cam.image_poll_timeout_ms          = int(self.timeout_ms)
                    cam.gain                           = int(self.gain)
                    cam.arm(2)
                    cam.issue_software_trigger()
                    frame = cam.get_pending_frame_or_null()
                    if frame is None:
                        cam.disarm()
                        self.error_signal.emit("Camera timeout — no frame received.")
                        return
                    img = frame_to_image(frame.image_buffer, camera_roi)
                    cam.disarm()
                    self.success_signal.emit(img)
        except Exception as e:
            self.error_signal.emit(str(e))


# ── OSA ───────────────────────────────────────────────────────────────────────
class OSAPingWorker(QThread):
    """Try a TCP connection to the OSA."""
    success_signal = pyqtSignal(str)
    error_signal   = pyqtSignal(str)

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        super().__init__()
        self.host    = host
        self.port    = port
        self.timeout = timeout

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            s.connect((self.host, self.port))
            s.close()
            self.success_signal.emit(f"Connected  {self.host}:{self.port}")
        except Exception as e:
            self.error_signal.emit(f"Cannot reach {self.host}:{self.port}  — {e}")


# ── OSA single scan ───────────────────────────────────────────────────────────
class OSAScanWorker(QThread):
    """Execute one OSA sweep and return (x_nm, y_nw) arrays."""
    data_signal   = pyqtSignal(np.ndarray, np.ndarray, str)
    status_signal = pyqtSignal(str)
    error_signal  = pyqtSignal(str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        cfg  = self.cfg
        host = cfg.get("osa_host", "192.168.0.1")
        port = cfg.get("osa_port", 10001)

        def _send(sock, msg):
            sock.send((msg + "\r\n").encode())
            time.sleep(0.05)

        def _query(sock, msg, timeout=10.0):
            """Send a query and receive the full response."""
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

        def _wait_sweep(sock, timeout_s=120):
            """Poll :stat:oper:even? until bit0 is set (sweep done)."""
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

        def _parse_trace(raw: str):
            """Parse comma-separated floats, skipping any header or non-numeric prefix."""
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
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(8)
            s.connect((host, port))
            s.settimeout(None)
            s.send(b'open "anonymous"\r\n'); time.sleep(0.2)
            s.send(b' \r\n');               time.sleep(0.2)
            self.status_signal.emit("Connected — configuring OSA...")
        except Exception as e:
            self.error_signal.emit(f"Connect failed: {e}")
            return

        try:
            _send(s, "*RST"); time.sleep(0.3)
            _send(s, "CFORM1")
            _send(s, f":sens:wav:star {cfg.get('osa_wl_start', 610.0)}nm")
            _send(s, f":sens:wav:stop {cfg.get('osa_wl_stop',  700.0)}nm")
            _send(s, f":sens:band:res {cfg.get('osa_resolution', 0.5)}nm")
            _send(s, f":sens:sens {cfg.get('osa_sensitivity', 'mid')}")
            _send(s, f":sens:sett:smo {cfg.get('osa_smoothing', 'OFF')}")
            _send(s, ":sens:sweep:points:auto off")
            _send(s, f":sens:sweep:step {cfg.get('osa_sampling', 0.05)}nm")
            _send(s, ":sens:corr:rvel:med air")
            _send(s, f":sens:aver:coun {cfg.get('osa_avg', 1)}")
            _send(s, ":sens:chop OFF")
            _send(s, ":DISPLAY:TRACE:Y1:SPACING LIN")
            _send(s, f":DISPLAY:TRACE:Y1:RLEVEL {cfg.get('osa_rlevel_nw', 2000)}nW")

            self.status_signal.emit("Sweeping — please wait...")
            _send(s, ":init:smode 1")
            _send(s, "*CLS")
            _send(s, ":init")

            if not _wait_sweep(s, 120):
                self.error_signal.emit("OSA sweep timed out (120s).")
                s.close()
                return

            self.status_signal.emit("Sweep done — reading trace...")

            raw_x = _query(s, ":TRAC:DATA:X? TRA", timeout=15)
            raw_y = _query(s, ":TRAC:DATA:Y? TRA", timeout=15)
            s.close()

            x_m  = _parse_trace(raw_x)
            y_w  = _parse_trace(raw_y)

            n = min(len(x_m), len(y_w))
            x_m = x_m[:n]
            y_w = y_w[:n]

            x_nm = x_m * 1e9
            y_nw = y_w * 1e9

            if len(x_nm) < 2:
                self.error_signal.emit(
                    f"Too few data points ({len(x_nm)}). "
                    f"Raw X starts with: {raw_x[:120]}"
                )
                return

            peak_idx = int(np.argmax(y_nw))
            info = (
                f"Peak: {x_nm[peak_idx]:.3f} nm  |  "
                f"{y_nw[peak_idx]:.1f} nW  |  "
                f"{len(x_nm)} points"
            )
            self.data_signal.emit(x_nm, y_nw, info)

        except Exception as e:
            self.error_signal.emit(f"Scan error: {e}")
            try:
                s.close()
            except Exception:
                pass


# ── PM100D power meter ────────────────────────────────────────────────────────
class PMTestWorker(QThread):
    """Connect to PM100D via VISA and read one power sample."""
    success_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)

    def __init__(self, visa_resource: str):
        super().__init__()
        self.visa_resource = visa_resource

    def run(self):
        from core.pm_meter import PM100DPowerMeter
        from core.power_math import watts_to_dbm

        pm = PM100DPowerMeter(self.visa_resource)
        try:
            pm.connect()
            watts = pm.read_power_watts()
            idn = pm.idn or self.visa_resource
            dbm = watts_to_dbm(watts)
            self.success_signal.emit(
                f"{idn}  |  {watts:.6e} W  ({dbm:.2f} dBm @ PM head)"
            )
        except Exception as exc:
            self.error_signal.emit(str(exc))
        finally:
            pm.close()


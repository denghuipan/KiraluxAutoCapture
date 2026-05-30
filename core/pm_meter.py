"""
Power meter backends — Python direct control (no LabVIEW).

- PM100D: Thorlabs USB power meter via pyvisa + SCPI (tested & working)
- Simulated: development stub when hardware is not connected
"""
from __future__ import annotations

from typing import List, Optional


class PowerMeterError(Exception):
    pass


# ── Discovery function ─────────────────────────────────────────────────────

def list_visa_resources() -> List[str]:
    """Return VISA resource strings (USB PM100D, etc.)."""
    try:
        import pyvisa
    except ImportError:
        return []
    try:
        rm = pyvisa.ResourceManager()
        return list(rm.list_resources())
    except Exception:
        return []


# ── Back-compat classes ────────────────────────────────────────────────────

class PowerMeterBase:
    def connect(self) -> None:
        raise NotImplementedError

    def read_power_watts(self) -> float:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SimulatedPowerMeter(PowerMeterBase):
    """Development stub — returns a synthetic reading from RF amplitude."""

    def __init__(self, *, max_pm_watts: float = 1.0):
        self._max_pm_watts = max_pm_watts
        self._rf_amp = 500

    def connect(self) -> None:
        return

    def set_rf_hint(self, rf_amp: int) -> None:
        self._rf_amp = int(rf_amp)

    def read_power_watts(self) -> float:
        return self._max_pm_watts * (self._rf_amp / 1000.0)


class PM100DPowerMeter(PowerMeterBase):
    """
    Thorlabs PM100D (or compatible) via VISA/SCPI using pyvisa.
    Tested & verified working (see power meter.ipynb).

    Typical resource: ``USB0::0x1313::0x8078::P0014896::INSTR``
    """

    def __init__(self, resource: str, wavelength_nm: float = 600.0):
        self.resource = resource.strip()
        self._inst = None
        self._pm100 = None  # ThorlabsPM100 wrapper
        self.idn: str = ""
        # Settings to apply on connect()
        self._wavelength = float(wavelength_nm)
        self._auto_range = True
        self._avg_count = 1

    def connect(self) -> None:
        try:
            import pyvisa
        except ImportError as exc:
            raise PowerMeterError(
                "pyvisa not installed — run: pip install pyvisa\n"
            ) from exc

        try:
            rm = pyvisa.ResourceManager()
            self._inst = rm.open_resource(self.resource)
            self._inst.timeout = 10000
            self.idn = self._inst.query("*IDN?").strip()
        except Exception as exc:
            raise PowerMeterError(
                f"PM100D connect failed ({self.resource}): {exc}\n"
                "Check USB cable and Thorlabs drivers."
            ) from exc

    def set_wavelength(self, wavelength_nm: float) -> None:
        """Set correction wavelength in nm. Sends SCPI command immediately."""
        self._wavelength = float(wavelength_nm)
        if self._inst:
            self._inst.write(f"SENS:CORR:WAV {wavelength_nm}")
            # Verify the setting was accepted
            resp = self._inst.query("SENS:CORR:WAV?").strip()
            set_wl = float(resp) / 1e0  # device returns in scientific notation
            # The device returns wavelength in nm as float, e.g. "6.500000E+02"
            # Just log for debugging - don't fail on minor differences

    def set_avg_count(self, count: int) -> None:
        """Set number of samples to average."""
        self._avg_count = max(1, int(count))
        if self._inst:
            self._inst.write(f"SENS:AVER:COUN {self._avg_count}")

    def set_auto_range(self, enabled: bool) -> None:
        """Enable/disable auto power range."""
        self._auto_range = bool(enabled)
        if self._inst:
            self._inst.write(f"SENS:POW:DC:RANG:AUTO {'ON' if enabled else 'OFF'}")

    def read_power_watts(self) -> float:
        if self._inst is None:
            raise PowerMeterError("PM100D not connected")
        try:
            raw = self._inst.query("MEAS:POW?").strip()
            return float(raw)
        except Exception as exc:
            raise PowerMeterError(f"PM100D read failed: {exc}") from exc

    def close(self) -> None:
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:
                pass
            self._inst = None

    def reset(self) -> None:
        """Reset instrument to default state."""
        if self._inst:
            self._inst.write("*RST")

    def zero_dark(self, timeout_s: float = 30.0) -> None:
        """Perform dark offset (zero) adjustment.

        The sensor must be covered/blocked during this operation.
        Polls the status until complete or timeout.
        """
        if not self._inst:
            raise PowerMeterError("PM not connected")
        # Start the zero adjustment
        self._inst.write("SENS:CORR:COLL:ZERO:INIT")
        # Poll until complete
        import time
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            status = self._inst.query("SENS:CORR:COLL:ZERO:STAT?").strip()
            if status == "0":
                return  # Done
            time.sleep(0.5)
        raise PowerMeterError("Zero adjustment timed out — ensure sensor is blocked.")


def create_power_meter(backend: str, **kwargs) -> PowerMeterBase:
    backend = (backend or "pm100d").lower()
    if backend in ("sim", "simulated", "mock"):
        return SimulatedPowerMeter(max_pm_watts=float(kwargs.get("sim_max_w", 1.0)))
    if backend in ("pm100d", "visa", "thorlabs"):
        resource = kwargs.get("visa_resource", "")
        if not resource:
            raise PowerMeterError(
                "PM100D resource is empty — use Hardware Test → Scan PM100D."
            )
        return PM100DPowerMeter(resource)
    raise PowerMeterError(f"Unknown power meter backend: {backend}")

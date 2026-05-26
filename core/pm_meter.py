"""
Power meter backends — Python direct control (no LabVIEW).

- PM100D: Thorlabs USB power meter via VISA/SCPI (pyvisa + NI-VISA)
- Simulated: development stub when hardware is not connected
"""
from __future__ import annotations

from typing import List, Optional


class PowerMeterError(Exception):
    pass


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
    Thorlabs PM100D (or compatible) via VISA/SCPI.

    Typical resource: ``USB0::0x1313::0x8078::P0001234::INSTR``
    """

    def __init__(self, resource: str):
        self.resource = resource.strip()
        self._inst = None
        self.idn: str = ""

    def connect(self) -> None:
        try:
            import pyvisa
        except ImportError as exc:
            raise PowerMeterError(
                "pyvisa not installed — run: pip install pyvisa\n"
                "Then install NI-VISA from ni.com or use pyvisa-py."
            ) from exc
        try:
            rm = pyvisa.ResourceManager()
            self._inst = rm.open_resource(self.resource)
            self._inst.timeout = 5000
            self.idn = self._inst.query("*IDN?").strip()
        except Exception as exc:
            raise PowerMeterError(
                f"PM100D connect failed ({self.resource}): {exc}\n"
                "Check USB cable, Thorlabs drivers, and NI-VISA."
            ) from exc

    def read_power_watts(self) -> float:
        if self._inst is None:
            raise PowerMeterError("PM100D not connected")
        for cmd in ("MEAS:POW?", "MEASure:SCALar:POWer?", ":READ?"):
            try:
                raw = self._inst.query(cmd).strip()
                return float(raw)
            except Exception:
                continue
        raise PowerMeterError("PM100D: could not read power (tried MEAS:POW?)")

    def close(self) -> None:
        if self._inst is not None:
            try:
                self._inst.close()
            except Exception:
                pass
            self._inst = None


def create_power_meter(backend: str, **kwargs) -> PowerMeterBase:
    backend = (backend or "pm100d").lower()
    if backend in ("sim", "simulated", "mock"):
        return SimulatedPowerMeter(max_pm_watts=float(kwargs.get("sim_max_w", 1.0)))
    if backend in ("pm100d", "visa", "thorlabs"):
        resource = kwargs.get("visa_resource", "")
        if not resource:
            raise PowerMeterError(
                "PM100D VISA resource is empty — use Hardware Test → Scan PM100D."
            )
        return PM100DPowerMeter(resource)
    raise PowerMeterError(f"Unknown power meter backend: {backend}")

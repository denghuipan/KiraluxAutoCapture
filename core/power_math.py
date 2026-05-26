"""
Optical power unit conversions for PM100D + coupling efficiency calibration.
"""
from __future__ import annotations

import math


def dbm_to_watts(dbm: float) -> float:
    """Convert dBm to watts (reference 1 mW)."""
    return 10.0 ** ((dbm - 30.0) / 10.0)


def watts_to_dbm(watts: float) -> float:
    if watts <= 0.0:
        return float("-inf")
    return 10.0 * math.log10(watts) + 30.0


def actual_watts_from_pm(pm_watts: float, coupling_efficiency: float) -> float:
    """Actual output power = PM reading × coupling efficiency."""
    return max(0.0, pm_watts) * max(0.0, coupling_efficiency)


def pm_watts_for_target(target_dbm: float, coupling_efficiency: float) -> float:
    """PM reading needed on the meter to reach target actual output."""
    eff = max(coupling_efficiency, 1e-30)
    return dbm_to_watts(target_dbm) / eff

"""
Iterative RF amplitude control to reach a target output power (via PM + coupling).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Optional

from core.power_math import (
    actual_watts_from_pm,
    dbm_to_watts,
    pm_watts_for_target,
    watts_to_dbm,
)


class RFPowerControlError(Exception):
    pass


class RFPowerMinReachedError(RFPowerControlError):
    """RF amplitude at floor but actual power still above target."""


class RFPowerMaxReachedError(RFPowerControlError):
    """RF amplitude at ceiling but actual power still below target."""


@dataclass
class RFPowerAdjustResult:
    rf_amplitude: int
    pm_reading_w: float
    actual_w: float
    actual_dbm: float
    target_dbm: float
    iterations: int


def adjust_rf_to_target(
    read_pm_watts: Callable[[], float],
    set_rf_amplitude: Callable[[int], None],
    *,
    target_dbm: float,
    coupling_efficiency: float,
    initial_amp: int = 500,
    min_amp: int = 10,
    max_amp: int = 1000,
    tolerance_db: float = 0.5,
    max_iterations: int = 40,
    settle_s: float = 0.5,
    pm_settle_s: float = 0.2,
    stop_check: Optional[Callable[[], bool]] = None,
) -> RFPowerAdjustResult:
    """
    Adjust RF amplitude until actual power (PM × coupling) matches target dBm.

    Safety: if RF drops to ``min_amp`` (default 10/1000) and power is still
    above target, raise ``RFPowerMinReachedError``.
    """
    if coupling_efficiency <= 0:
        raise RFPowerControlError("Coupling efficiency must be > 0")
    if min_amp < 0 or max_amp > 1000 or min_amp >= max_amp:
        raise RFPowerControlError("Invalid RF amplitude limits")

    amp = int(max(min_amp, min(max_amp, initial_amp)))
    target_w = dbm_to_watts(target_dbm)
    pm_target_w = pm_watts_for_target(target_dbm, coupling_efficiency)

    set_rf_amplitude(amp)
    time.sleep(settle_s)

    last_pm = 0.0
    last_actual_w = 0.0
    last_actual_dbm = float("-inf")

    for iteration in range(1, max_iterations + 1):
        if stop_check and stop_check():
            raise RFPowerControlError("Stop requested during RF adjustment")

        time.sleep(pm_settle_s)
        last_pm = float(read_pm_watts())
        last_actual_w = actual_watts_from_pm(last_pm, coupling_efficiency)
        last_actual_dbm = watts_to_dbm(last_actual_w)

        err_db = last_actual_dbm - target_dbm
        if abs(err_db) <= tolerance_db:
            return RFPowerAdjustResult(
                rf_amplitude=amp,
                pm_reading_w=last_pm,
                actual_w=last_actual_w,
                actual_dbm=last_actual_dbm,
                target_dbm=target_dbm,
                iterations=iteration,
            )

        if last_actual_dbm > target_dbm:
            # Need less power — decrease RF
            if amp <= min_amp:
                raise RFPowerMinReachedError(
                    f"RF amplitude at minimum ({min_amp}/1000) but actual power "
                    f"{last_actual_dbm:.2f} dBm still above target {target_dbm:.2f} dBm "
                    f"(PM={last_pm:.3e} W, coupling={coupling_efficiency:.3e}). "
                    "Check attenuator / coupling calibration."
                )
            if last_actual_w > 0 and target_w > 0:
                ratio = target_w / last_actual_w
                amp = int(round(amp * (ratio ** 0.65)))
            else:
                amp = max(min_amp, amp // 2)
            amp = max(min_amp, min(amp, max_amp - 1))
        else:
            # Need more power — increase RF
            if amp >= max_amp:
                raise RFPowerMaxReachedError(
                    f"RF amplitude at maximum ({max_amp}/1000) but actual power "
                    f"{last_actual_dbm:.2f} dBm still below target {target_dbm:.2f} dBm."
                )
            if last_actual_w > 0 and target_w > 0:
                ratio = target_w / last_actual_w
                amp = int(round(amp * (ratio ** 0.65)))
            else:
                amp = min(max_amp, max(amp + 50, amp * 2))
            amp = min(max_amp, max(amp, min_amp + 1))

        set_rf_amplitude(amp)
        time.sleep(settle_s)

    raise RFPowerControlError(
        f"RF adjustment did not converge in {max_iterations} iterations "
        f"(last {last_actual_dbm:.2f} dBm vs target {target_dbm:.2f} dBm, "
        f"PM target ≈ {pm_target_w:.3e} W)."
    )

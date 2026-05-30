"""
RF amplitude control to reach a target output power (via PM + coupling).

Four strategies:
- ``adjust_rf_to_target``       — iterative jump-and-settle (legacy, slow)
- ``sweep_rf_to_target``        — bidirectional 0.1% steps from initial RF
- ``ramp_rf_to_target``         — linear ramp from ceiling, no laser cycling
- ``servo_rf_to_target_bisect`` — binary search (bisection) bracket servo
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
    overshoot_trigger: bool = False
    status: str = "ok"
    # "ok" | "bracket_overflow_low" | "bracket_overflow_high"
    # | "bisect_converged_out_of_band"


# ── Legacy: iterative jump-and-settle ──────────────────────────────────────

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


# ── New: fast continuous sweep ─────────────────────────────────────────────

def sweep_rf_to_target(
    read_pm_watts: Callable[[], float],
    set_rf_amplitude: Callable[[int], None],
    *,
    target_dbm: float,
    coupling_efficiency: float,
    initial_amp: int = 500,
    min_amp: int = 10,
    max_amp: int = 1000,
    tolerance_db: float = 0.5,
    max_sweep_steps: int = 990,
    settle_s: float = 1.0,
    verify_count: int = 3,
    pm_read_delay: float = 0.05,
    stop_check: Optional[Callable[[], bool]] = None,
) -> RFPowerAdjustResult:
    """
    Fast continuous sweep to reach target power.

    Strategy:
    1. Start at initial_amp, read PM once to determine direction
    2. Sweep continuously in 1-unit (0.1%) steps with only PM read delay
    3. Once inside tolerance, pause (settle_s) for laser to stabilize
    4. Verify stability with ``verify_count`` consecutive reads
    5. Return result if all verifications pass

    Safety: raises ``RFPowerMinReachedError`` / ``RFPowerMaxReachedError``
    if sweep hits a boundary without entering tolerance.
    """
    if coupling_efficiency <= 0:
        raise RFPowerControlError("Coupling efficiency must be > 0")

    amp = int(max(min_amp, min(max_amp, initial_amp)))
    target_w = dbm_to_watts(target_dbm)

    # Phase 0 — initial reading to determine sweep direction
    set_rf_amplitude(amp)
    time.sleep(0.3)
    last_pm = float(read_pm_watts())
    last_actual_w = actual_watts_from_pm(last_pm, coupling_efficiency)
    last_actual_dbm = watts_to_dbm(last_actual_w)

    err_db = last_actual_dbm - target_dbm
    if abs(err_db) <= tolerance_db:
        # Already in range
        _sweep_settle_and_verify(
            read_pm_watts, coupling_efficiency, amp,
            target_dbm, tolerance_db, settle_s, verify_count, pm_read_delay,
            stop_check,
        )
        return RFPowerAdjustResult(
            rf_amplitude=amp, pm_reading_w=last_pm,
            actual_w=last_actual_w, actual_dbm=last_actual_dbm,
            target_dbm=target_dbm, iterations=1,
        )

    direction = -1 if last_actual_dbm > target_dbm else +1
    steps = 0
    iteration = 1

    while steps < max_sweep_steps:
        if stop_check and stop_check():
            raise RFPowerControlError("Stop requested during RF sweep")

        amp += direction
        if amp < min_amp:
            raise RFPowerMinReachedError(
                f"Sweep hit minimum RF ({min_amp}/1000) "
                f"without reaching target {target_dbm:.2f} dBm."
            )
        if amp > max_amp:
            raise RFPowerMaxReachedError(
                f"Sweep hit maximum RF ({max_amp}/1000) "
                f"without reaching target {target_dbm:.2f} dBm."
            )

        set_rf_amplitude(amp)
        time.sleep(pm_read_delay)
        last_pm = float(read_pm_watts())
        last_actual_w = actual_watts_from_pm(last_pm, coupling_efficiency)
        last_actual_dbm = watts_to_dbm(last_actual_w)
        steps += 1
        iteration += 1

        if abs(last_actual_dbm - target_dbm) <= tolerance_db:
            # Inside tolerance — settle + verify
            result = _sweep_settle_and_verify(
                read_pm_watts, coupling_efficiency, amp,
                target_dbm, tolerance_db, settle_s, verify_count, pm_read_delay,
                stop_check,
            )
            return RFPowerAdjustResult(
                rf_amplitude=amp,
                pm_reading_w=result[0],
                actual_w=result[1],
                actual_dbm=result[2],
                target_dbm=target_dbm,
                iterations=iteration,
            )

        # Safety: if we're moving away from target (overshot direction),
        # reverse direction with small step
        new_err = last_actual_dbm - target_dbm
        if (direction == -1 and new_err < err_db - 2.0) or \
           (direction == +1 and new_err > err_db + 2.0):
            direction = -direction

        err_db = new_err

    raise RFPowerControlError(
        f"RF sweep did not reach target in {max_sweep_steps} steps "
        f"(last {last_actual_dbm:.2f} dBm vs target {target_dbm:.2f} dBm)."
    )


def _sweep_settle_and_verify(
    read_pm_watts: Callable[[], float],
    coupling_efficiency: float,
    amp: int,
    target_dbm: float,
    tolerance_db: float,
    settle_s: float,
    verify_count: int,
    pm_read_delay: float,
    stop_check: Optional[Callable[[], bool]],
) -> tuple:
    """Settle and verify after finding in-range RF amplitude."""
    time.sleep(settle_s)
    last_pm = float(read_pm_watts())
    last_actual_w = actual_watts_from_pm(last_pm, coupling_efficiency)
    last_actual_dbm = watts_to_dbm(last_actual_w)

    if stop_check and stop_check():
        raise RFPowerControlError("Stop requested during verify phase")

    # Verify stability
    for _ in range(verify_count):
        time.sleep(pm_read_delay)
        pm_val = float(read_pm_watts())
        act_w = actual_watts_from_pm(pm_val, coupling_efficiency)
        act_dbm = watts_to_dbm(act_w)
        if abs(act_dbm - target_dbm) > tolerance_db:
            # Drifted out of range — return to sweep caller for adjustment
            raise RFPowerControlError(
                f"Power drifted out of tolerance during verify: "
                f"{act_dbm:.2f} dBm (target {target_dbm:.2f} dBm)"
            )
        last_pm = pm_val
        last_actual_w = act_w
        last_actual_dbm = act_dbm

    return last_pm, last_actual_w, last_actual_dbm


# ── Servo: amplitude-only, trigger + settle + verify (no laser cycling) ─────

def servo_rf_to_target(
    read_pm_watts: Callable[[], float],
    set_rf_amplitude: Callable[[int], None],
    *,
    target_dbm: float,
    coupling_efficiency: float,
    start_amp: int = 0,
    min_amp: int = 10,
    max_amp: int = 1000,
    tolerance_db: float = 0.5,
    step_interval_ms: float = 50.0,
    settle_s: float = 1.0,
    pm_sample_s: float = 0.1,
    verify_count: int = 3,
    stop_check: Optional[Callable[[], bool]] = None,
    pm_callback: Optional[
        Callable[[float, int, float, float, float, str], None]
    ] = None,
) -> RFPowerAdjustResult:
    """
    Reach target power by ramping RF **from low to high only** (amplitude +1 steps).

    1. Start at ``min_amp``, read PM.
    2. Increase RF by 0.1% per step until power is inside the tolerance band, **or**
       one step crosses **above** ``target + tolerance`` — then use **that** reading
       and RF (no revert), lock amplitude, short settle, capture.
    3. Normal in-band trigger: full settle + verify.

    ``start_amp`` is ignored (always begins at ``min_amp``).
    """
    if coupling_efficiency <= 0:
        raise RFPowerControlError("Coupling efficiency must be > 0")

    step_delay = max(0.01, step_interval_ms / 1000.0)
    sample_delay = max(0.02, float(pm_sample_s))
    amp = int(min_amp)
    t0 = time.perf_counter()
    iteration = 0
    upper_cross = False

    def _report(phase: str, pm_w: float, act_w: float, act_dbm: float) -> None:
        if pm_callback is not None:
            pm_callback(time.perf_counter() - t0, amp, pm_w, act_w, act_dbm, phase)

    def _read() -> tuple:
        pm_w = float(read_pm_watts())
        act_w = actual_watts_from_pm(pm_w, coupling_efficiency)
        act_dbm = watts_to_dbm(act_w)
        return pm_w, act_w, act_dbm

    def _in_band(act_dbm: float) -> bool:
        return abs(act_dbm - target_dbm) <= tolerance_db

    def _above_upper(act_dbm: float) -> bool:
        return act_dbm > target_dbm + tolerance_db

    set_rf_amplitude(amp)
    time.sleep(min(0.3, step_delay))

    last_pm, last_actual_w, last_actual_dbm = _read()
    iteration += 1
    _report("adjust", last_pm, last_actual_w, last_actual_dbm)

    if _above_upper(last_actual_dbm):
        upper_cross = True
    elif not _in_band(last_actual_dbm):
        while True:
            if stop_check and stop_check():
                raise RFPowerControlError("Stop requested during RF adjustment")

            if amp >= max_amp:
                raise RFPowerMaxReachedError(
                    f"RF at maximum ({max_amp}/1000) but actual "
                    f"{last_actual_dbm:.2f} dBm has not reached target "
                    f"{target_dbm:.2f} dBm (±{tolerance_db} dB)."
                )

            was_below_upper = not _above_upper(last_actual_dbm)
            amp += 1
            set_rf_amplitude(amp)
            time.sleep(step_delay)
            last_pm, last_actual_w, last_actual_dbm = _read()
            iteration += 1
            _report("adjust", last_pm, last_actual_w, last_actual_dbm)

            if _in_band(last_actual_dbm):
                break
            if _above_upper(last_actual_dbm):
                upper_cross = was_below_upper or upper_cross
                break

    trigger_phase = "overshoot" if upper_cross else "triggered"
    _report(trigger_phase, last_pm, last_actual_w, last_actual_dbm)

    if upper_cross:
        time.sleep(min(sample_delay, 0.1))
        last_pm, last_actual_w, last_actual_dbm = _read()
        iteration += 1
        _report("settle", last_pm, last_actual_w, last_actual_dbm)
    else:
        settle_end = time.perf_counter() + settle_s
        while time.perf_counter() < settle_end:
            if stop_check and stop_check():
                raise RFPowerControlError("Stop requested during settle")
            time.sleep(sample_delay)
            last_pm, last_actual_w, last_actual_dbm = _read()
            iteration += 1
            _report("settle", last_pm, last_actual_w, last_actual_dbm)
            # Settle is a pure time delay after trigger — do not gate on in-band

        for _ in range(verify_count):
            if stop_check and stop_check():
                raise RFPowerControlError("Stop requested during verify")
            time.sleep(sample_delay)
            last_pm, last_actual_w, last_actual_dbm = _read()
            iteration += 1
            _report("verify", last_pm, last_actual_w, last_actual_dbm)
            # If power drifted, report via callback but return best-effort result

    return RFPowerAdjustResult(
        rf_amplitude=amp,
        pm_reading_w=last_pm,
        actual_w=last_actual_w,
        actual_dbm=last_actual_dbm,
        target_dbm=target_dbm,
        iterations=iteration,
        overshoot_trigger=upper_cross,
    )


# ── Binary search (bisection) servo ───────────────────────────────────────────

def servo_rf_to_target_bisect(
    read_pm_watts: Callable[[], float],
    set_rf_amplitude: Callable[[int], None],
    *,
    target_dbm: float,
    coupling_efficiency: float,
    start_amp: int = 0,
    min_amp: int = 10,
    max_amp: int = 1000,
    tolerance_db: float = 0.5,
    step_interval_ms: float = 50.0,
    settle_s: float = 1.0,
    pm_sample_s: float = 0.1,
    verify_count: int = 3,
    stop_check: Optional[Callable[[], bool]] = None,
    pm_callback: Optional[
        Callable[[float, int, float, float, float, str], None]
    ] = None,
    max_bisect_iter: int = 20,
) -> RFPowerAdjustResult:
    """
    Reach target power via **binary search** (bisection) on RF amplitude.

    Bracket ``[min_amp, max_amp]`` is verified before bisecting:

    - If ``max_amp`` is already below target → use ``max_amp`` directly.
    - If ``min_amp`` is already above target → use ``min_amp`` directly.

    Each bisection step sets ``amp_mid = (amp_lo + amp_hi) // 2``, reads the PM,
    and narrows the bracket.  Stops when inside ``tolerance_db`` or when the
    bracket collapses to ≤ 1 unit.  The best amplitude seen (closest dBm to
    target) is used for the final settle+verify phase.

    If the target is never reached within tolerance, the best-effort amplitude
    is still used and a normal result is returned (no exception raised).

    ``pm_callback`` signature: ``(t_sec, amp, pm_w, act_w, act_dbm, phase)``
    Phases emitted: ``"bisect_lo"``, ``"bisect_hi"``, ``"bisect"``,
                    ``"settle"``, ``"verify"``.
    """
    if coupling_efficiency <= 0:
        raise RFPowerControlError("Coupling efficiency must be > 0")

    pm_read_delay = max(0.01, step_interval_ms / 1000.0)
    sample_delay = max(0.02, float(pm_sample_s))
    t0 = time.perf_counter()
    iteration = 0

    def _report(phase: str, amp: int, pm_w: float, act_w: float, act_dbm: float) -> None:
        if pm_callback is not None:
            pm_callback(time.perf_counter() - t0, amp, pm_w, act_w, act_dbm, phase)

    def _read(amp: int) -> tuple:
        set_rf_amplitude(amp)
        time.sleep(pm_read_delay)
        pm_w = float(read_pm_watts())
        act_w = actual_watts_from_pm(pm_w, coupling_efficiency)
        act_dbm = watts_to_dbm(act_w)
        return pm_w, act_w, act_dbm

    def _in_band(act_dbm: float) -> bool:
        return abs(act_dbm - target_dbm) <= tolerance_db

    # ── Verify bracket ────────────────────────────────────────────────────────
    amp_lo = int(min_amp)
    amp_hi = int(max_amp)

    if stop_check and stop_check():
        raise RFPowerControlError("Stop requested during RF bisect setup")

    pm_lo, act_lo_w, act_lo_dbm = _read(amp_lo)
    iteration += 1
    _report("bisect_lo", amp_lo, pm_lo, act_lo_w, act_lo_dbm)

    if stop_check and stop_check():
        raise RFPowerControlError("Stop requested during RF bisect setup")

    pm_hi, act_hi_w, act_hi_dbm = _read(amp_hi)
    iteration += 1
    _report("bisect_hi", amp_hi, pm_hi, act_hi_w, act_hi_dbm)

    # Early-exit: already in band at a boundary
    best_amp = amp_lo
    best_dist = abs(act_lo_dbm - target_dbm)
    last_pm, last_actual_w, last_actual_dbm = pm_lo, act_lo_w, act_lo_dbm
    _bracket_status = "ok"

    if abs(act_hi_dbm - target_dbm) < best_dist:
        best_amp = amp_hi
        best_dist = abs(act_hi_dbm - target_dbm)
        last_pm, last_actual_w, last_actual_dbm = pm_hi, act_hi_w, act_hi_dbm

    if _in_band(act_lo_dbm):
        best_amp = amp_lo
        last_pm, last_actual_w, last_actual_dbm = pm_lo, act_lo_w, act_lo_dbm
    elif _in_band(act_hi_dbm):
        best_amp = amp_hi
        last_pm, last_actual_w, last_actual_dbm = pm_hi, act_hi_w, act_hi_dbm
    elif act_hi_dbm < target_dbm:
        # max_amp still below target — best we can do is max_amp
        best_amp = amp_hi
        last_pm, last_actual_w, last_actual_dbm = pm_hi, act_hi_w, act_hi_dbm
        _bracket_status = "bracket_overflow_low"
        _report("bracket_overflow_low", amp_hi, pm_hi, act_hi_w, act_hi_dbm)
    elif act_lo_dbm > target_dbm:
        # min_amp already above target — best we can do is min_amp
        best_amp = amp_lo
        last_pm, last_actual_w, last_actual_dbm = pm_lo, act_lo_w, act_lo_dbm
        _bracket_status = "bracket_overflow_high"
        _report("bracket_overflow_high", amp_lo, pm_lo, act_lo_w, act_lo_dbm)
    else:
        # ── Bisection loop ────────────────────────────────────────────────────
        for _ in range(max_bisect_iter):
            if stop_check and stop_check():
                raise RFPowerControlError("Stop requested during RF bisect")

            amp_mid = (amp_lo + amp_hi) // 2
            pm_mid, act_mid_w, act_mid_dbm = _read(amp_mid)
            iteration += 1
            _report("bisect", amp_mid, pm_mid, act_mid_w, act_mid_dbm)

            dist = abs(act_mid_dbm - target_dbm)
            if dist < best_dist:
                best_amp = amp_mid
                best_dist = dist
                last_pm, last_actual_w, last_actual_dbm = pm_mid, act_mid_w, act_mid_dbm

            if _in_band(act_mid_dbm):
                break

            if act_mid_dbm < target_dbm:
                amp_lo = amp_mid     # need more power → raise floor
            else:
                amp_hi = amp_mid     # need less power → lower ceiling

            if amp_hi - amp_lo <= 1:
                break   # bracket converged; best_amp already recorded

    # ── Settle phase ──────────────────────────────────────────────────────────
    set_rf_amplitude(best_amp)
    settle_end = time.perf_counter() + settle_s
    while time.perf_counter() < settle_end:
        if stop_check and stop_check():
            raise RFPowerControlError("Stop requested during bisect settle")
        time.sleep(sample_delay)
        pm_s = float(read_pm_watts())
        act_s_w = actual_watts_from_pm(pm_s, coupling_efficiency)
        act_s_dbm = watts_to_dbm(act_s_w)
        iteration += 1
        _report("settle", best_amp, pm_s, act_s_w, act_s_dbm)
        last_pm, last_actual_w, last_actual_dbm = pm_s, act_s_w, act_s_dbm

    # ── Verify phase ──────────────────────────────────────────────────────────
    for _ in range(verify_count):
        if stop_check and stop_check():
            raise RFPowerControlError("Stop requested during bisect verify")
        time.sleep(sample_delay)
        pm_v = float(read_pm_watts())
        act_v_w = actual_watts_from_pm(pm_v, coupling_efficiency)
        act_v_dbm = watts_to_dbm(act_v_w)
        iteration += 1
        _report("verify", best_amp, pm_v, act_v_w, act_v_dbm)
        last_pm, last_actual_w, last_actual_dbm = pm_v, act_v_w, act_v_dbm

    return RFPowerAdjustResult(
        rf_amplitude=best_amp,
        pm_reading_w=last_pm,
        actual_w=last_actual_w,
        actual_dbm=last_actual_dbm,
        target_dbm=target_dbm,
        iterations=iteration,
        overshoot_trigger=False,
        status=_bracket_status,
    )


# ── Linear ramp: ceiling → target (legacy; test data uses servo_rf_to_target) ─

def ramp_rf_to_target(
    read_pm_watts: Callable[[], float],
    set_rf_amplitude: Callable[[int], None],
    *,
    target_dbm: float,
    coupling_efficiency: float,
    min_amp: int = 10,
    max_amp: int = 1000,
    tolerance_db: float = 0.5,
    step_interval_ms: float = 50.0,
    settle_s: float = 1.0,
    verify_count: int = 3,
    stop_check: Optional[Callable[[], bool]] = None,
    pm_callback: Optional[Callable[[int, float, float, float], None]] = None,
) -> RFPowerAdjustResult:
    """
    Linear ramp from ceiling (max_amp) downward to target — no backtracking,
    no laser cycling.

    Strategy:
    1. Set RF to ceiling (max_amp = 1000)
    2. Ramp down: every ``step_interval_ms``, decrease RF by 1 (0.1%)
    3. Read PM after each step — no extra settle delay
    4. When power enters tolerance band → settle + verify + return
    5. If ramp crosses below target without hitting tolerance →
       trigger at the closest point encountered

    Laser stays on throughout the entire ramp.

    ``pm_callback`` is called after each PM reading with (amp, pm_W, actual_W, actual_dbm).
    """
    if coupling_efficiency <= 0:
        raise RFPowerControlError("Coupling efficiency must be > 0")

    step_delay = step_interval_ms / 1000.0
    amp = max_amp
    set_rf_amplitude(amp)
    time.sleep(0.3)  # brief initial settle

    # Track closest point to target (fallback if we cross without hitting tolerance)
    best_amp = amp
    best_dist_db = float("inf")

    iteration = 1

    while amp >= min_amp:
        if stop_check and stop_check():
            raise RFPowerControlError("Stop requested during RF ramp")

        last_pm = float(read_pm_watts())
        last_actual_w = actual_watts_from_pm(last_pm, coupling_efficiency)
        last_actual_dbm = watts_to_dbm(last_actual_w)
        dist_db = abs(last_actual_dbm - target_dbm)

        # Report current reading to callback
        if pm_callback is not None:
            pm_callback(amp, last_pm, last_actual_w, last_actual_dbm)

        # Track the closest reading we've seen
        if dist_db < best_dist_db:
            best_amp = amp
            best_dist_db = dist_db

        # Check tolerance
        if dist_db <= tolerance_db:
            result = _ramp_settle_and_verify(
                read_pm_watts, coupling_efficiency, amp,
                target_dbm, tolerance_db, settle_s, verify_count,
                step_delay, stop_check, pm_callback,
            )
            return RFPowerAdjustResult(
                rf_amplitude=amp,
                pm_reading_w=result[0],
                actual_w=result[1],
                actual_dbm=result[2],
                target_dbm=target_dbm,
                iterations=iteration,
            )

        # Crossed below target without entering tolerance — stop at closest point
        if last_actual_dbm < target_dbm:
            if best_dist_db > tolerance_db:
                break

        iteration += 1
        amp -= 1
        set_rf_amplitude(amp)
        time.sleep(step_delay)

    # Fell through — trigger at closest point with settle
    result = _ramp_settle_and_verify(
        read_pm_watts, coupling_efficiency, best_amp,
        target_dbm, tolerance_db, settle_s, verify_count,
        step_delay, stop_check,
    )
    return RFPowerAdjustResult(
        rf_amplitude=best_amp,
        pm_reading_w=result[0],
        actual_w=result[1],
        actual_dbm=result[2],
        target_dbm=target_dbm,
        iterations=iteration,
    )


def _ramp_settle_and_verify(
    read_pm_watts: Callable[[], float],
    coupling_efficiency: float,
    amp: int,
    target_dbm: float,
    tolerance_db: float,
    settle_s: float,
    verify_count: int,
    min_delay: float,
    stop_check: Optional[Callable[[], bool]],
    pm_callback: Optional[Callable[[int, float, float, float], None]] = None,
) -> tuple:
    """Settle and verify after ramp finds in-range RF amplitude."""
    time.sleep(settle_s)
    last_pm = float(read_pm_watts())
    last_actual_w = actual_watts_from_pm(last_pm, coupling_efficiency)
    last_actual_dbm = watts_to_dbm(last_actual_w)

    if pm_callback is not None:
        pm_callback(amp, last_pm, last_actual_w, last_actual_dbm)

    if stop_check and stop_check():
        raise RFPowerControlError("Stop requested during verify phase")

    for _ in range(verify_count):
        time.sleep(min_delay)
        pm_val = float(read_pm_watts())
        act_w = actual_watts_from_pm(pm_val, coupling_efficiency)
        act_dbm = watts_to_dbm(act_w)

        if pm_callback is not None:
            pm_callback(amp, pm_val, act_w, act_dbm)

        if abs(act_dbm - target_dbm) > tolerance_db:
            raise RFPowerControlError(
                f"Power drifted out of tolerance during verify: "
                f"{act_dbm:.2f} dBm (target {target_dbm:.2f} dBm)"
            )
        last_pm = pm_val
        last_actual_w = act_w
        last_actual_dbm = act_dbm

    return last_pm, last_actual_w, last_actual_dbm

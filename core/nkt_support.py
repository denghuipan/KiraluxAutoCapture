"""
NKT Photonics SDK helpers — path setup, discovery, and control functions.

Every function here mirrors the exact notebook code from kiralux_capture.ipynb.
Register read/write calls do NOT require an open port (the SDK does dedicated
reads internally), so openPorts is only called during discovery and then closed.
"""
from __future__ import annotations

import os
import sys
import time
from typing import List, Optional, Tuple


def project_data_dir() -> str:
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    here = os.path.dirname(os.path.abspath(__file__))
    autocapture = os.path.dirname(here)
    return os.path.dirname(autocapture)


def nkt_folder() -> str:
    return os.path.join(project_data_dir(), "NKT")


def _nkt_arch_subdir() -> str:
    import struct
    return "x64" if struct.calcsize("P") == 8 else "x86"


def _pe_machine(path: str) -> Optional[int]:
    """Return PE machine type (0x8664=AMD64, 0x14C=i386) or None."""
    try:
        import struct
        with open(path, "rb") as f:
            f.seek(0x3C)
            pe_off = struct.unpack("<I", f.read(4))[0]
            f.seek(pe_off + 4)
            return struct.unpack("<H", f.read(2))[0]
    except OSError:
        return None


def _dll_matches_python(path: str) -> bool:
    want = 0x8664 if _nkt_arch_subdir() == "x64" else 0x14C
    got = _pe_machine(path)
    return got == want


def resolve_nkt_dll_path() -> Optional[str]:
    """
    Locate NKTPDLL.dll matching Python bitness — prefer project-local copies.

    Supported layouts (first valid match wins):
      {project}/NKT/NKTPDLL/x64/NKTPDLL.dll   (or x86)
      {project}/NKT SDK/NKTPDLL/x64/NKTPDLL.dll
      {project}/NKT/NKTPDLL.dll               (only if arch matches)
      NKTP_SDK_PATH / NKTPDLL / x64 / NKTPDLL.dll
      D:\\NKT SDK\\NKTPDLL\\x64\\NKTPDLL.dll
    """
    arch = _nkt_arch_subdir()
    root = project_data_dir()
    nkt = nkt_folder()

    candidates = [
        os.path.join(root, "NKTPDLL", arch, "NKTPDLL.dll"),
        os.path.join(nkt, "NKTPDLL", arch, "NKTPDLL.dll"),
        os.path.join(root, "NKT SDK", "NKTPDLL", arch, "NKTPDLL.dll"),
    ]
    env_sdk = os.environ.get("NKTP_SDK_PATH", "").strip()
    if env_sdk:
        candidates.insert(
            0, os.path.join(env_sdk, "NKTPDLL", arch, "NKTPDLL.dll")
        )
    env_dll = os.environ.get("NKTP_DLL_PATH", "").strip()
    if env_dll:
        candidates.insert(0, env_dll)
    candidates.extend([
        os.path.join(nkt, "NKTPDLL.dll"),
        os.path.join(r"D:\NKT SDK", "NKTPDLL", arch, "NKTPDLL.dll"),
    ])

    for path in candidates:
        if path and os.path.isfile(path) and _dll_matches_python(path):
            return os.path.abspath(path)
    return None


def describe_nkt_dll_problem() -> str:
    """Human-readable hint when NKTPDLL cannot be loaded."""
    arch = _nkt_arch_subdir()
    root = project_data_dir()
    nkt = nkt_folder()
    flat = os.path.join(nkt, "NKTPDLL.dll")
    if os.path.isfile(flat) and not _dll_matches_python(flat):
        found = _pe_machine(flat)
        found_name = "x86 (32-bit)" if found == 0x14C else hex(found or 0)
        return (
            f"Found {flat} but it is {found_name}; this app needs {arch} Python "
            f"and a matching {arch} NKTPDLL.dll.\n"
            f"Copy from the NKT SDK installer:\n"
            f"  NKTPDLL\\{arch}\\NKTPDLL.dll\n"
            f"to:\n"
            f"  {os.path.join(nkt, 'NKTPDLL', arch, 'NKTPDLL.dll')}"
        )
    return (
        f"No {arch} NKTPDLL.dll found. Place it at:\n"
        f"  {os.path.join(root, 'NKTPDLL', arch, 'NKTPDLL.dll')}\n"
        f"  or  {os.path.join(nkt, 'NKTPDLL', arch, 'NKTPDLL.dll')}"
    )


def prepare_nkt_environment() -> Tuple[bool, Optional[str]]:
    """Add NKT folder to sys.path / PATH and resolve NKTPDLL.dll locally."""
    d = nkt_folder()
    if not os.path.isdir(d):
        return False, f"NKT folder not found: {d}"
    if d not in sys.path:
        sys.path.insert(0, d)
    os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(d)
        except OSError:
            pass

    dll_path = resolve_nkt_dll_path()
    if not dll_path:
        return False, describe_nkt_dll_problem()

    os.environ["NKTP_DLL_PATH"] = dll_path
    dll_dir = os.path.dirname(dll_path)
    os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(dll_dir)
        except OSError:
            pass
    return True, None


def _split_ports(s: str) -> List[str]:
    return [p.strip() for p in s.split(",") if p.strip()]


# ── Discovery (mirrors notebook Cell 8 exactly) ──────────────────────────────

def discover_nkt_modules(
    preferred_comport: Optional[str] = None,
    settle_s: float = 0.5,
) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Scan all ports for NKT modules, then close.

    Returns (comport, extreme_addr, rf_addr, superk_addr, error).
    On failure: all fields None except error.
    """
    ok, err = prepare_nkt_environment()
    if not ok:
        return None, None, None, None, err

    try:
        from NKTP_DLL import (
            closePorts,
            deviceGetAllTypes,
            getAllPorts,
            getLegacyBusScanning,
            getOpenPorts,
            openPorts,
            PortResultTypes,
        )
    except Exception as e:
        return None, None, None, None, f"NKTP_DLL import failed: {e}"

    pref = None
    if preferred_comport and not preferred_comport.startswith("(no ports"):
        pref = preferred_comport.strip()

    try:
        _ = getLegacyBusScanning()
        all_list = getAllPorts().strip()
        portnames = all_list if all_list else ""
        op_res = openPorts(portnames, 1, 1)
        if op_res != 0:
            closePorts("")
            return None, None, None, None, (
                f"openPorts failed: {PortResultTypes(op_res)} "
                f"(listed={all_list or '(empty)'})"
            )

        time.sleep(settle_s)
        opened = getOpenPorts().strip()
        if not opened:
            closePorts("")
            return None, None, None, None, (
                "getOpenPorts empty — no NKT modules detected on any port. "
                "Close other NKT apps, check USB, or try a different cable/port."
            )

        candidates = []
        for port_name in _split_ports(opened):
            extreme = extreme61 = rf = sk = None
            _status, dev_list = deviceGetAllTypes(port_name)
            for dev_id in range(len(dev_list)):
                t = int(dev_list[dev_id])
                if t == 0:
                    continue
                if t == 0x60:
                    extreme = dev_id
                elif t == 0x61:
                    extreme61 = dev_id
                elif t == 0x66:
                    rf = dev_id
                elif t == 0x67:
                    sk = dev_id

            ext_addr = extreme if extreme is not None else extreme61
            if rf is not None and ext_addr is not None:
                candidates.append((port_name, ext_addr, rf, sk))

        closePorts("")

        if not candidates:
            return None, None, None, None, (
                f"No complete NKT stack (Extreme + RF 0x66) on: {opened}"
            )

        chosen = None
        if pref:
            for row in candidates:
                if row[0].upper() == pref.upper():
                    chosen = row
                    break
        if chosen is None:
            chosen = candidates[0]

        com, ext_addr, rf, sk = chosen
        return com, ext_addr, rf, sk, None

    except Exception as e:
        try:
            from NKTP_DLL import closePorts as _close
            _close("")
        except Exception:
            pass
        return None, None, None, None, str(e)


# ── Exact copies of notebook Cell 10 functions ────────────────────────────────


def Extreme_turnON(comport: str, extreme: int, emissionpercent: int) -> None:
    """Notebook Cell 10: Extreme_turnON — constant power mode, set emission, turn ON."""
    from NKTP_DLL import registerRead, registerWriteU8, registerWriteU16

    status = registerRead(comport, extreme, 0x66, -1)
    time.sleep(0.5)
    if int.from_bytes(status[1], "little") & 0x01 == 0x00:
        registerWriteU16(comport, extreme, 0x31, 0x01, -1)
        time.sleep(0.2)
        emission = emissionpercent * 10
        registerWriteU16(comport, extreme, 0x37, emission, -1)
        time.sleep(0.2)
        registerWriteU8(comport, extreme, 0x30, 0x03, -1)
        time.sleep(0.5)


def crystal_select(
    comport: str, RF_power: int, SuperK_select: int, crystal_num: int
) -> None:
    """Notebook Cell 10: crystal_select — 0=Vis/NIR, 1=NIR/IR."""
    if SuperK_select is None or SuperK_select < 0:
        return
    from NKTP_DLL import registerRead, registerWriteU8

    result = registerRead(comport, RF_power, 0x75, -1)
    time.sleep(0.2)
    if int.from_bytes(result[1], "little") != (crystal_num + 1):
        registerWriteU8(comport, RF_power, 0x30, 0x00, -1)
        time.sleep(0.2)
        registerWriteU8(comport, SuperK_select, 0x34, 0x00, -1)
        time.sleep(0.2)
        result = registerRead(comport, RF_power, 0x75, -1)
        time.sleep(0.2)
        if int.from_bytes(result[1], "little") != (crystal_num + 1):
            registerWriteU8(comport, SuperK_select, 0x34, 0x01, -1)
            time.sleep(0.2)
        registerWriteU8(comport, SuperK_select, 0x35, crystal_num, -1)
        time.sleep(0.2)
        registerRead(comport, RF_power, 0x75, -1)
        time.sleep(0.2)


def RF_turnON(comport: str, RF_power: int) -> None:
    """Notebook Cell 10: RF_turnON — zero all 8 channels, then enable RF."""
    from NKTP_DLL import registerRead, registerWriteU8, registerWriteU16

    for i in range(8):
        registerWriteU16(comport, RF_power, 0xB0 + i, 0, -1)
        time.sleep(0.2)
    status = registerRead(comport, RF_power, 0x66, -1)
    if int.from_bytes(status[1], "little") & 0x01 == 0x00:
        registerWriteU8(comport, RF_power, 0x30, 0x01, -1)
        time.sleep(0.2)


def RF_turnOFF(comport: str, RF_power: int) -> None:
    """Notebook Cell 10: RF_turnOFF."""
    from NKTP_DLL import registerWriteU8

    registerWriteU8(comport, RF_power, 0x30, 0x00, -1)
    time.sleep(0.2)


def Extreme_turnOFF(comport: str, extreme: int) -> None:
    """Notebook Cell 10: Extreme_turnOFF."""
    from NKTP_DLL import registerWriteU8

    registerWriteU8(comport, extreme, 0x30, 0x00, -1)
    time.sleep(0.2)


def set_nkt(comport: str, RF_power: int, wavelength_pm: int) -> int:
    """Notebook Cell 10: set_nkt — write wavelength in picometers to RF 0x90."""
    from NKTP_DLL import registerWriteU32

    result = registerWriteU32(comport, RF_power, 0x90, wavelength_pm, -1)
    time.sleep(0.2)
    return result


def nkt_safety_init(
    comport: str,
    extreme: int,
    RF_power: int,
    emission_pct: int = 100,
) -> None:
    """
    Notebook Cell 30 safety init — UNCONDITIONAL writes (no status checks).
    Must be called once before the main loop and can be called per-step.
    """
    from NKTP_DLL import registerWriteU8, registerWriteU16

    registerWriteU8(comport, extreme, 0x30, 0x03, -1)
    time.sleep(0.1)
    emission = emission_pct * 10
    registerWriteU16(comport, extreme, 0x37, emission, -1)
    time.sleep(0.1)
    registerWriteU8(comport, RF_power, 0x30, 0x01, -1)
    time.sleep(0.1)
    registerWriteU16(comport, RF_power, 0xB0, 1000, -1)
    time.sleep(0.1)


def set_channel_amplitude(
    comport: str,
    RF_power: int,
    amplitude: int,
    channel: int = 0,
) -> None:
    """Update RF channel amplitude only (RF stays enabled, no other channels touched)."""
    from NKTP_DLL import registerWriteU16

    ch = int(channel)
    if ch < 0 or ch > 7:
        raise ValueError("channel must be 0..7")
    registerWriteU16(comport, RF_power, 0xB0 + ch, int(amplitude), -1)
    time.sleep(0.05)


def set_channel_wavelength_amplitude(
    comport: str,
    RF_power: int,
    wavelength_nm: float,
    amplitude: int,
    channel: int = 0,
) -> None:
    """Set one channel wavelength + amplitude only (RF stays on, no channel zeroing)."""
    from NKTP_DLL import registerWriteU16, registerWriteU32

    ch = int(channel)
    if ch < 0 or ch > 7:
        raise ValueError("channel must be 0..7")
    registerWriteU32(comport, RF_power, 0x90 + ch, int(wavelength_nm * 1000), -1)
    time.sleep(0.05)
    registerWriteU16(comport, RF_power, 0xB0 + ch, int(amplitude), -1)
    time.sleep(0.05)


def set_single_channel(
    comport: str,
    RF_power: int,
    wavelength_nm: float,
    amplitude: int,
    channel: int = 0,
) -> None:
    """Set one RF channel wavelength/amplitude; zero all others."""
    from NKTP_DLL import registerWriteU16, registerWriteU32

    ch = int(channel)
    if ch < 0 or ch > 7:
        raise ValueError("channel must be 0..7")
    for i in range(8):
        registerWriteU16(comport, RF_power, 0xB0 + i, 0, -1)
        time.sleep(0.05)
    registerWriteU32(comport, RF_power, 0x90 + ch, int(wavelength_nm * 1000), -1)
    time.sleep(0.05)
    registerWriteU16(comport, RF_power, 0xB0 + ch, int(amplitude), -1)
    time.sleep(0.05)


def nkt_test_emit(
    comport: str,
    extreme: int,
    RF_power: int,
    amplitude: int,
    wavelength_nm: float,
) -> None:
    """
    Notebook Cell 27 "test NKT" — unconditional bring-up sequence:
    1) Read extreme status → emission ON → emission 100%
    2) Read RF status → RF ON
    3) Set RF ch0 amplitude → read back
    4) Set wavelength
    """
    from NKTP_DLL import (
        registerRead, registerWriteU8, registerWriteU16, registerWriteU32,
    )

    registerRead(comport, extreme, 0x66, -1)
    time.sleep(0.1)
    registerWriteU8(comport, extreme, 0x30, 0x03, -1)
    time.sleep(0.1)
    registerWriteU16(comport, extreme, 0x37, 1000, -1)
    time.sleep(0.1)

    registerRead(comport, RF_power, 0x66, -1)
    time.sleep(0.1)
    registerWriteU8(comport, RF_power, 0x30, 0x01, -1)
    time.sleep(0.1)

    registerWriteU16(comport, RF_power, 0xB0, int(amplitude), -1)
    time.sleep(0.1)
    registerRead(comport, RF_power, 0xB0, -1)
    time.sleep(0.1)

    registerWriteU32(comport, RF_power, 0x90, int(wavelength_nm * 1000), -1)
    time.sleep(0.1)


def nkt_full_shutdown(comport: str, extreme: int, RF_power: int) -> None:
    """
    Notebook Cell 28 — full shutdown sequence:
    1) Extreme emission OFF → verify
    2) RF OFF → ch0 amplitude 0 → verify
    """
    from NKTP_DLL import registerRead, registerWriteU8, registerWriteU16

    registerWriteU8(comport, extreme, 0x30, 0x00, -1)
    time.sleep(0.1)
    registerRead(comport, extreme, 0x66, -1)
    time.sleep(0.1)

    registerRead(comport, RF_power, 0x66, -1)
    time.sleep(0.1)
    registerWriteU8(comport, RF_power, 0x30, 0x00, -1)
    time.sleep(0.1)

    registerWriteU16(comport, RF_power, 0xB0, 0, -1)
    time.sleep(0.1)
    registerRead(comport, RF_power, 0xB0, -1)
    time.sleep(0.1)


# ── Shared multi-channel helpers (used by LoopRunner AND TestDataRunner) ──────

def set_multipeaks_config(
    comport: str,
    extreme: int,
    rf: int,
    emission_pct: int,
    wavelengths: List[float],
    amplitudes: List[int],
) -> None:
    """Apply a full multi-channel NKT config.

    Zeros all 8 amplitude channels, then writes each (wavelength, amplitude) pair.
    Call via nkt_thread.call() from any runner thread.
    """
    from NKTP_DLL import registerWriteU8, registerWriteU16, registerWriteU32

    registerWriteU8(comport, extreme, 0x30, 0x03, -1)
    time.sleep(0.05)
    registerWriteU16(comport, extreme, 0x37, int(emission_pct) * 10, -1)
    time.sleep(0.05)
    registerWriteU8(comport, rf, 0x30, 0x01, -1)
    time.sleep(0.05)

    for i in range(8):
        registerWriteU16(comport, rf, 0xB0 + i, 0, -1)
        time.sleep(0.05)
    for i, (wl, amp) in enumerate(zip(wavelengths, amplitudes)):
        registerWriteU32(comport, rf, 0x90 + i, int(float(wl) * 1000), -1)
        time.sleep(0.05)
        registerWriteU16(comport, rf, 0xB0 + i, int(amp), -1)
        time.sleep(0.05)


def _random_wavelengths_gen(
    rng,
    wl_min: float,
    wl_max: float,
    n_ch: int,
    sp_min: float,
    sp_max: float,
) -> List[float]:
    """Pick n_ch sorted wavelengths in [wl_min, wl_max] with random spacing.

    Adjacent channel spacing drawn from Uniform(sp_min, sp_max);
    the whole group is randomly placed within the range.
    """
    import numpy as _np

    if n_ch <= 0:
        return []
    if n_ch == 1:
        return [round(float(rng.uniform(wl_min, wl_max)), 1)]

    max_fit = max(1, int((wl_max - wl_min) / max(sp_min, 1e-6)) + 1)
    n_ch = min(n_ch, max_fit)
    if n_ch == 1:
        return [round(float(rng.uniform(wl_min, wl_max)), 1)]

    gaps = rng.uniform(sp_min, sp_max, size=n_ch - 1)
    total_span = float(gaps.sum())
    if total_span > wl_max - wl_min:
        gaps = gaps * ((wl_max - wl_min) / total_span)
        total_span = float(gaps.sum())

    slack = wl_max - wl_min - total_span
    start = wl_min + float(rng.uniform(0, max(slack, 0)))
    pts = [start]
    for g in gaps:
        pts.append(pts[-1] + float(g))
    return [round(p, 1) for p in pts]


def build_nkt_step_configs(cfg: dict) -> List[dict]:
    """Generate NKT step configs from a loop config dict.

    Returns a list of ``{"wavelengths": [...], "amplitudes": [...]}`` dicts,
    one per loop step.  Logic mirrors LoopRunner._build_configs exactly so
    both runners produce identical sequences for the same seed.
    """
    import numpy as _np

    mode = int(cfg.get("mode", 0))
    n_steps = int(cfg.get("n_steps", 10))

    # ── Single Peak Scan ──────────────────────────────────────────────────
    if mode == 2:
        wl_min = float(cfg.get("single_wl_min", 620.0))
        wl_max = float(cfg.get("single_wl_max", 690.0))
        step = float(cfg.get("single_step", 0.5))
        amp = int(cfg.get("single_amp", 1000))
        candidates = _np.round(_np.arange(wl_min, wl_max + step * 0.5, step), 1)
        return [{"wavelengths": [float(w)], "amplitudes": [amp]} for w in candidates]

    # ── Manual Multi-Peak ─────────────────────────────────────────────────
    if mode == 1:
        wls = list(cfg.get("manual_wavelengths", []))
        amps = list(cfg.get("manual_amplitudes", []))
        if not wls:
            return []
        return [{"wavelengths": wls, "amplitudes": amps}] * n_steps

    # ── Broadband (mode == 3) ─────────────────────────────────────────────
    if mode == 3:
        bb_seed         = int(cfg.get("bb_seed", cfg.get("seed", 42)))
        bb_amp_mode     = cfg.get("bb_amp_mode", "fixed")
        bb_amp_fixed    = int(cfg.get("bb_amp_fixed", cfg.get("bb_amp_equal", 500)))
        bb_amp_min_v    = int(cfg.get("bb_amp_min", 200))
        bb_amp_max_v    = int(cfg.get("bb_amp_max", 1000))
        bb_amp_manual   = [int(a) for a in cfg.get("bb_amp_manual", [500] * 8)]
        bb_emission     = int(cfg.get("bb_emission_pct", 100))
        bb_spacing_primary = bool(cfg.get("bb_spacing_primary", False))

        rng = _np.random.default_rng(bb_seed)
        step_cfgs = []
        for _ in range(n_steps):
            # 1. Determine spacing (primary driver)
            if bb_spacing_primary:
                if cfg.get("bb_spacing_mode", "fixed") == "fixed":
                    spacing = float(cfg.get("bb_spacing_fixed", 10.0 / 7.0))
                else:
                    spacing = float(rng.uniform(
                        cfg.get("bb_spacing_min", 1.0),
                        cfg.get("bb_spacing_max", 2.0),
                    ))
                span = spacing * 7.0
            else:
                if cfg.get("bb_span_mode", "fixed") == "fixed":
                    span = float(cfg.get("bb_span_fixed", 10.0))
                else:
                    span = float(rng.uniform(
                        cfg.get("bb_span_min", 5.0),
                        cfg.get("bb_span_max", 20.0),
                    ))
                spacing = span / 7.0

            # 2. Center wavelength
            if cfg.get("bb_center_mode", "fixed") == "fixed":
                center = float(cfg.get("bb_center_fixed", 645.0))
            else:
                center = float(rng.uniform(
                    cfg.get("bb_center_min", 620.0),
                    cfg.get("bb_center_max", 670.0),
                ))

            # 3. 8 channel wavelengths evenly spaced around center
            offsets = _np.linspace(-span / 2.0, span / 2.0, 8)
            wls = _np.clip(center + offsets, 500.0, 900.0).tolist()
            wls = [round(w, 1) for w in wls]

            # 4. Amplitudes
            if bb_amp_mode == "fixed":
                amps = [bb_amp_fixed] * 8
            elif bb_amp_mode == "random":
                amps = rng.integers(bb_amp_min_v, bb_amp_max_v + 1, size=8).tolist()
            else:  # manual
                amps = (bb_amp_manual + [500] * 8)[:8]

            label = (
                f"BB center={center:.1f}nm  "
                f"span={span:.2f}nm  "
                f"sp={spacing:.3f}nm  "
                f"amps={amps}"
            )
            step_cfgs.append({
                "wavelengths": wls,
                "amplitudes":  amps,
                "emission":    bb_emission,
                "label":       label,
            })
        return step_cfgs

    # ── Absorption Peak (mode == 4) ───────────────────────────────────────
    if mode == 4:
        import numpy as _np2
        n_steps      = cfg.get("absorp_steps", 50)
        spacing      = float(cfg.get("absorp_spacing_nm", 1.0))
        baseline_amp = int(cfg.get("absorp_baseline_amp", 1000))
        rng          = _np2.random.default_rng(cfg.get("absorp_seed", 42))
        step_cfgs    = []

        for _ in range(n_steps):
            # Center wavelength
            if cfg.get("absorp_center_mode", "fixed") == "fixed":
                center = float(cfg.get("absorp_center_fixed", 645))
            else:
                center = float(rng.uniform(
                    cfg.get("absorp_center_min", 625),
                    cfg.get("absorp_center_max", 665),
                ))

            # 8 channel wavelengths with configurable spacing
            wls = [center + (i - 3.5) * spacing for i in range(8)]
            wls = [max(500.0, min(900.0, w)) for w in wls]

            # Number of absorption dips
            if cfg.get("absorp_ndips_mode", "fixed") == "fixed":
                n_dips = int(cfg.get("absorp_ndips_fixed", 2))
            else:
                n_dips = int(rng.integers(
                    cfg.get("absorp_ndips_min", 1),
                    cfg.get("absorp_ndips_max", 4) + 1,
                ))
            n_dips = max(0, min(8, n_dips))

            # Select which channels are absorbed
            dip_indices = rng.choice(8, size=n_dips, replace=False).tolist()

            # Build amplitude array: baseline for all, random dip for selected
            amps = [baseline_amp] * 8
            dip_min = int(cfg.get("absorp_dip_amp_min", 200))
            dip_max = int(cfg.get("absorp_dip_amp_max", 800))
            for idx in dip_indices:
                amps[idx] = int(rng.integers(dip_min, dip_max + 1))

            label = (
                f"Absorp center={center:.1f}nm  "
                f"spacing={spacing:.2f}nm  "
                f"ndips={n_dips}  "
                f"dip=[{dip_min},{dip_max}]"
            )
            step_cfgs.append({
                "wavelengths": wls,
                "amplitudes":  amps,
                "emission":    int(cfg.get("absorp_emission_pct", 100)),
                "label":       label,
            })
        return step_cfgs

    # ── Random Multi-Peak (mode == 0) ─────────────────────────────────────
    seed = int(cfg.get("seed", 42))
    wl_min = float(cfg.get("wl_min", 620))
    wl_max = float(cfg.get("wl_max", 690))
    spacing_mode = int(cfg.get("spacing_mode", 0))
    wl_step = float(cfg.get("wl_step", 5))
    spacing_min = float(cfg.get("spacing_min", 0.1))
    spacing_max = float(cfg.get("spacing_max", 1.0))
    ch_min = int(cfg.get("n_ch_min", 2))
    ch_max = int(cfg.get("n_ch_max", 8))
    amp_min = int(cfg.get("amp_min", 200))
    amp_max = int(cfg.get("amp_max", 1000))
    rng = _np.random.default_rng(seed)

    if spacing_mode == 0:
        wl_candidates = _np.round(
            _np.arange(wl_min, wl_max + wl_step * 0.5, wl_step), 1
        )
        if len(wl_candidates) == 0:
            return []
        configs = []
        for _ in range(n_steps):
            n_ch = int(_np.clip(rng.integers(ch_min, ch_max + 1), 1, len(wl_candidates)))
            idx = rng.choice(len(wl_candidates), size=n_ch, replace=False)
            wls = sorted(wl_candidates[idx].tolist())
            amps = rng.integers(amp_min, amp_max + 1, size=len(wls)).tolist()
            configs.append({"wavelengths": wls, "amplitudes": amps})
        return configs

    configs = []
    for _ in range(n_steps):
        n_ch = int(rng.integers(ch_min, ch_max + 1))
        wls = _random_wavelengths_gen(rng, wl_min, wl_max, n_ch, spacing_min, spacing_max)
        amps = rng.integers(amp_min, amp_max + 1, size=len(wls)).tolist()
        configs.append({"wavelengths": wls, "amplitudes": amps})
    return configs

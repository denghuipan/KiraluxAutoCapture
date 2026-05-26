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

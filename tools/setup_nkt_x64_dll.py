"""Copy x64 NKTPDLL.dll into project NKT/NKTPDLL/x64/ if found."""
import os
import shutil
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEST_DIR = os.path.join(ROOT, "NKT", "NKTPDLL", "x64")
DEST = os.path.join(DEST_DIR, "NKTPDLL.dll")

CANDIDATES = [
    os.path.join(ROOT, "NKTPDLL", "x64", "NKTPDLL.dll"),
    os.path.join(ROOT, "NKT", "NKTPDLL", "x64", "NKTPDLL.dll"),
    os.path.join(ROOT, "NKT", "NKTPDLL.dll"),
    r"C:\Users\pande\Desktop\KiraluxAutoCapture\_internal\NKT\NKTPDLL.dll",
    r"D:\NKT SDK\NKTPDLL\x64\NKTPDLL.dll",
    os.path.join(ROOT, "NKT SDK", "NKTPDLL", "x64", "NKTPDLL.dll"),
]


def pe_machine(path: str):
    with open(path, "rb") as f:
        f.seek(0x3C)
        pe = struct.unpack("<I", f.read(4))[0]
        f.seek(pe + 4)
        return struct.unpack("<H", f.read(2))[0]


def main():
    for src in CANDIDATES:
        if not os.path.isfile(src):
            continue
        m = pe_machine(src)
        arch = "x64" if m == 0x8664 else "x86" if m == 0x14C else hex(m)
        print(f"{src} -> {arch}")
        if m == 0x8664:
            os.makedirs(DEST_DIR, exist_ok=True)
            shutil.copy2(src, DEST)
            print(f"Copied to {DEST}")
            return 0
    print("No x64 NKTPDLL.dll found. Install NKT SDK and copy:")
    print(f"  NKTPDLL\\x64\\NKTPDLL.dll  ->  {DEST}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

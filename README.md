# Kiralux AutoCapture

Automated image acquisition system for optical experiments. Integrates Thorlabs Kiralux cameras, NKT SuperK lasers, Yokogawa OSA spectrometers, and power meters into a single PyQt5 GUI.

## Requirements

- Windows 10/11
- Python 3.9+
- Hardware SDK DLLs (see [Setup](#setup))

## Quick Start

```bash
pip install -r requirements.txt
python main.py
```

### Setup

Place the following directories alongside `autocapture/` (see project root):

- `Native_64_lib/` — Thorlabs native DLLs
- `NKT/` — NKT Photonics SDK
- `NKTPDLL/x64/` — NKT DLL
- `thorlabs_tsi_sdk/` — Thorlabs camera SDK
- `roi_processor/` — ROI processing

## Features

| Tab | Purpose |
|-----|---------|
| Hardware Test | Verify all device connections |
| Camera | ROI, exposure, gain, image save |
| NKT Laser | Wavelength & power control |
| Auto Loop | Automated multi-step acquisition |
| OSA | Spectrum scanning |
| Test Data | Playback & analysis |

## Build Executable

```bash
pyinstaller KiraluxAutoCapture.spec --noconfirm --clean
```

## License

For research use only.

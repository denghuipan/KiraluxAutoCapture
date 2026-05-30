# Kiralux AutoCapture

Automated image acquisition and training data generation system for optical experiments. Integrates Thorlabs Kiralux cameras, NKT SuperK lasers, Yokogawa OSA spectrometers, and PM100D power meters into a single PyQt5 GUI.

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

Place the following directories alongside `autocapture/`:

| Directory | Purpose |
|-----------|---------|
| `Native_64_lib/` | Thorlabs native DLLs |
| `NKT/` | NKT Photonics SDK + `NKTPDLL/x64/` |
| `thorlabs_tsi_sdk/` | Thorlabs camera SDK |
| `roi_processor/` | ROI crop pipeline (also bundled inside) |

## Features

### Hardware

| Device | Interface |
|--------|-----------|
| Thorlabs Kiralux camera | USB 3.0 (SDK) |
| NKT SuperK Extreme + SELECT | USB/COM (serial) |
| Yokogawa OSA AQ6370D | TCP/IP |
| Thorlabs PM100D | USB/VISA (PyVISA) |

### 6 Tabs

| Tab | Purpose |
|-----|---------|
| Hardware Test | Verify all device connections |
| Camera | ROI, exposure/gain, live preview, auto crop, H5 export |
| NKT Laser | COM port, crystal (VIS/NIR), 8-channel manual table |
| Auto Loop | 5 capture modes, multi-round training strategy, inline test set |
| Test Data | RF power servo to target dBm, live power trace, bright field pre-capture |
| OSA | TCP spectrum scanning, Savitzky-Golay reduction, H5 export |

### Capture Modes (Auto Loop)

| Mode | Description |
|------|-------------|
| **Random Multi-Peak** | N steps with random wavelengths (fixed grid or fully random spacing) |
| **Manual Multi-Peak** | Fixed 8-channel config from NKT tab, repeated N times |
| **Single Peak Scan** | Wavelength sweep (start → end, configurable step) |
| **Broadband** | 8 channels with configurable span/center/spacing/amplitude |
| **Absorption Peak** | 8 channels with configurable absorption dips (baseline + reduced amplitudes) |

### Training Strategy

- Up to 50 independent rounds, each with its own mode and parameters
- Save/restore per-round config with status tracking
- Inline test set: after each round, auto-capture a reproducible test subset

### RF Power Servo (Test Data)

- Set target power (dBm) with coupling efficiency
- Two algorithms: linear ramp or binary search
- Live power monitor (stream PM readings without touching laser)
- Real-time color-coded power-vs-time chart
- Bright field pre-capture: multi-exposure images at full RF before servo

### Other

- **Auto ROI crop**: max-sum sliding window, outputs TIFF + PNG per frame
- **HDF5 export**: paired image/OSA datasets with contrast preprocessing
- **OSA-only mode**: NKT + OSA without camera
- **Dark/Light themes** (Catppuccin) with live preview

## Build Executable

```bash
pyinstaller KiraluxAutoCapture.spec --noconfirm --clean
```

Or run `build_exe.bat` from the `autocapture/` directory.

## License

For research use only.

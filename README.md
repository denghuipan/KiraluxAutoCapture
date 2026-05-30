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

### Hardware Integration

| Device | Interface | Capabilities |
|--------|-----------|--------------|
| **Thorlabs Kiralux** camera | USB 3.0 (SDK) | ROI, exposure (0.03–22806 ms), gain, live preview |
| **NKT SuperK** Extreme + SELECT | USB/COM | Multi-channel wavelength + RF amplitude control |
| **Yokogawa OSA** AQ6370D | TCP/IP | Spectrum scanning, Savitzky-Golay reduction |
| **Thorlabs PM100D** | USB/VISA | Power measurement, dark adjustment, live monitor |

### 6 Tab GUI

| Tab | Purpose |
|-----|---------|
| **Hardware Test** | Scan NKT ports, laser bring-up (3-step), test camera/OSA/PM100D |
| **Camera** | ROI, exposure, gain, auto-crop, image save (TIFF/NPY/DAT), live preview |
| **NKT Laser** | COM port, crystal (VIS/NIR), 8-channel manual table, test emit |
| **Auto Loop** | 4 capture modes × 50 training rounds, config CSV export |
| **OSA** | TCP connection, sweep params, live spectrum plot, H5 export |
| **Test Data** | RF power servo to target dBm, live power trace, per-step CSV logs |

### Capture Modes (Auto Loop)

| Mode | Description |
|------|-------------|
| **Random Multi-Peak** | N steps with random wavelengths (fixed grid or fully random spacing), configurable amplitude range |
| **Manual Multi-Peak** | Fixed 8-channel config from NKT tab, repeated N times |
| **Single Peak Scan** | Wavelength sweep (start → end, configurable step) |
| **Broadband** | 8 channels with ~10 nm span, center wavelength control, 3 amplitude modes |

### Training Strategy

- Up to **50 independent rounds**, each with its own capture mode and parameters
- Save/restore per-round config with status tracking
- Total capture count shown before start

### RF Power Servo (Test Data Tab)

- Set **target power (dBm)** with coupling efficiency (scientific notation)
- Two servo algorithms: **linear ramp** and **binary search**
- **Live power monitor** before test — stream PM readings without touching NKT/RF
- Real-time color-coded power-vs-time chart with target band
- Per-step PM trace CSV with phase labels

### Auto ROI Cropping

- Max-sum sliding window algorithm (configurable signal/outer dimensions)
- Outputs cropped TIFF + PNG preview per frame
- Shared between Camera tab and Test Data tab

### HDF5 Dataset Export

- **Image H5**: paired image + labels (`roundXX_loopYY_j`), gzip compressed, optional contrast preprocessing (vmin/vmax clip + scale)
- **OSA H5**: reduced spectra (Savitzky-Golay smoothing + downsample to N points) with wavelength axis validation
- Thread-safe append with shape validation

### Other

- **OSA-only mode** — NKT + OSA without camera
- **Dark/Light themes** (Catppuccin) with live preview
- **PyInstaller** executable build (`build_exe.bat`)

## Build Executable

```bash
pyinstaller KiraluxAutoCapture.spec --noconfirm --clean
```

Or run `build_exe.bat` from the `autocapture/` directory.

## Project Structure

```
autocapture/
├── main.py                      # Entry point
├── requirements.txt             # Dependencies
├── KiraluxAutoCapture.spec      # PyInstaller spec
├── build_exe.bat                # Build script
├── README.md
├── MANUAL_en.md / MANUAL_zh.md  # User manuals
│
├── core/                        # Business logic
│   ├── app_settings.py          # Theme + font (QSettings)
│   ├── camera_support.py        # Camera SDK wrapper
│   ├── h5_store.py              # HDF5 writers (image + OSA)
│   ├── hw_tester.py             # Hardware diagnostics
│   ├── image_contrast.py        # vmin/vmax preprocessing
│   ├── loop_runner.py           # Auto loop engine (QThread)
│   ├── nkt_support.py           # NKT SDK wrapper
│   ├── nkt_thread.py            # Dedicated NKT thread
│   ├── osa_reduce.py            # Savitzky-Golay reduction
│   ├── pm_meter.py              # PM100D / simulated power meter
│   ├── power_math.py            # dBm/W conversions
│   ├── rf_power_control.py      # RF servo algorithms
│   ├── roi_postprocess.py       # Auto crop pipeline
│   ├── sample_label.py          # Paired label generator
│   └── test_data_runner.py      # Test data engine (QThread)
│
├── ui/                          # GUI tabs
│   ├── main_window.py           # Main window + shared status bar
│   ├── settings_dialog.py       # Theme + font settings
│   ├── tab_camera.py            # Camera tab
│   ├── tab_hardware_test.py     # Hardware test tab
│   ├── tab_loop.py              # Auto loop tab
│   ├── tab_nkt.py               # NKT laser tab
│   ├── tab_osa.py               # OSA tab
│   ├── tab_test_data.py         # Test data tab
│   └── layout_helpers.py        # Layout utilities
│
├── roi_processor/core/          # ROI algorithms
│   ├── roi_finder.py            # Max-sum sliding window
│   └── image_io.py              # TIFF/PNG I/O
│
└── tools/
    └── setup_nkt_x64_dll.py     # NKT DLL setup utility
```

## License

For research use only.

# Kiralux AutoCapture

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/UI-PyQt5-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)](https://github.com/denghuipan/KiraluxAutoCapture)

**Kiralux AutoCapture** is an integrated automated image acquisition system for optical experiments. It coordinates Thorlabs Kiralux cameras, NKT SuperK lasers, Yokogawa OSA spectrometers, and power meters for automated multi-device scanning and data collection.

---

## Features

| Module | Description |
|--------|-------------|
| **📷 Camera Control** | Thorlabs Kiralux camera control with ROI configuration, exposure/gain adjustment, live view, and image saving (TIFF / HDF5) |
| **🔦 Laser Control** | NKT SuperK Extreme + SELECT control with multi-channel wavelength configuration, RF power adjustment, and random wavelength generation |
| **📊 Spectrum Analysis** | Yokogawa OSA control over TCP/IP with spectrum acquisition and dimensionality reduction (Savitzky-Golay smoothing) |
| **⚡ Power Meter** | Power meter data acquisition and real-time monitoring via PyVISA |
| **🔄 Auto Scan Loop** | Multi-wavelength sweep with configurable ROI, auto-exposure, and automatic data saving (HDF5 / TIFF / CSV) |
| **🛠 Hardware Test** | Integrated hardware diagnostics panel for quick verification of all device connections |
| **📁 Playback & Analysis** | Test data replay and post-processing tools |

---

## Supported Hardware

| Device | Model | Interface | Status |
|--------|-------|-----------|--------|
| Thorlabs Kiralux Camera | CS505MUP & full series | USB 3.0 (thorlabs_tsi_sdk) | ✅ Supported |
| NKT SuperK Laser | SuperK Extreme + SELECT | USB/COM (serial) | ✅ Supported |
| NKT RF Module | RF module | USB/COM (serial) | ✅ Supported |
| Yokogawa OSA | AQ6370D series | TCP/IP | ✅ Supported |
| Power Meter | Devices compatible with PyVISA | USB/TCP | ✅ Supported |

---

## Requirements

- **OS**: Windows 10/11 (requires thorlabs_tsi_sdk native DLL)
- **Python**: 3.9+
- **Recommended environment**: Conda `DNN` environment

### Dependencies

```
PyQt5>=5.15.0
numpy>=1.24.0
matplotlib>=3.7.0
pyserial>=3.5
tifffile>=2023.1.1
scipy>=1.10.0
h5py>=3.8.0
pyinstaller>=6.0.0
pyvisa>=1.14.0
pyvisa-py>=0.7.0
zeroconf>=0.130.0
```

---

## Quick Start

### 1. Install Dependencies

```bash
conda activate DNN
pip install -r requirements.txt
```

### 2. Run the Application

```bash
python main.py
```

Or use the `Run DNN` task in VS Code.

### 3. Build Executable

```bat
build_exe.bat
```

Output: `dist_release\KiraluxAutoCapture_v2\KiraluxAutoCapture_v2.exe`

---

## Project Structure

```
autocapture/
├── main.py                      # Application entry point
├── requirements.txt             # Python dependencies
├── KiraluxAutoCapture.spec      # PyInstaller build spec
├── build_exe.bat                # Build script
├── .gitignore
├── README.md
├── MANUAL_en.md                 # User manual (English)
├── MANUAL_zh.md                 # User manual (Chinese)
│
├── core/                        # Core business logic
│   ├── app_settings.py          # App settings & theme (dark/light)
│   ├── camera_support.py        # Kiralux camera SDK wrapper
│   ├── h5_store.py              # HDF5 data storage
│   ├── hw_tester.py             # Hardware diagnostics
│   ├── image_contrast.py        # Image contrast adjustment
│   ├── loop_runner.py           # Auto acquisition loop engine (QThread)
│   ├── nkt_support.py           # NKT laser SDK wrapper
│   ├── nkt_thread.py            # Dedicated NKT thread (avoids IBHandler conflicts)
│   ├── osa_reduce.py            # OSA spectrum dimensionality reduction / smoothing
│   ├── pm_meter.py              # Power meter control
│   ├── power_math.py            # Power calculation utilities
│   ├── rf_power_control.py      # RF power control
│   ├── roi_postprocess.py       # ROI post-processing
│   ├── sample_label.py          # Sample label management
│   └── test_data_runner.py      # Test data replay engine
│
├── ui/                          # Graphical user interface
│   ├── main_window.py           # Main application window
│   ├── settings_dialog.py       # Settings dialog
│   ├── style_helpers.py         # Style helpers
│   ├── tab_camera.py            # Camera control tab
│   ├── tab_hardware_test.py     # Hardware test tab
│   ├── tab_loop.py              # Auto loop tab
│   ├── tab_nkt.py               # NKT laser control tab
│   ├── tab_osa.py               # OSA spectrum tab
│   └── tab_test_data.py         # Test data replay tab
│
└── tools/
    └── setup_nkt_x64_dll.py     # NKT DLL environment setup
```

**External dependency directories** (located in the project parent folder):

```
../Native_64_lib/       # Native 64-bit DLLs
../NKT/                 # NKT Photonics SDK + NKTPDLL
../NKTPDLL/             # NKTPDLL x64 DLL
../thorlabs_tsi_sdk/    # Thorlabs TSI SDK
../roi_processor/       # ROI processor
```

---

## Getting Started

### First Use — Hardware Test

1. Open the app and go to the **Hardware Test** tab
2. Click **Scan all NKT ports** to discover the laser COM ports
3. Follow the steps: Extreme ON → RF ON → Apply emission
4. Click **Capture Test Frame** to verify camera connection
5. Click **Ping OSA** to test spectrometer connectivity

### Auto Acquisition Loop

1. Switch to the **Camera** tab to set ROI, exposure, and gain
2. In the **NKT** tab, configure laser wavelengths and power
3. Go to the **Loop** tab and configure scan parameters
4. Click **Start Loop** to begin automated acquisition

### Data Formats

- **Images**: TIFF (single frame) / HDF5 (multi-frame sequences)
- **Spectra**: CSV
- **Logs**: Plain text log files

---

## Notes

> ⚠ Windows may reassign COM ports after USB reconnection — simply re-scan to restore connections.
>
> ⚠ The NKT DLL (NKTP_DLL) must be initialized in a dedicated thread to avoid Qt IBHandler cross-thread errors.
>
> ⚠ After building an executable, some DLLs may need to be copied from `_internal/` to the executable directory.

---

## License

This project is for internal research use only.

---

## Contact

- Author: Denghui Pan
- GitHub: [denghuipan/KiraluxAutoCapture](https://github.com/denghuipan/KiraluxAutoCapture)

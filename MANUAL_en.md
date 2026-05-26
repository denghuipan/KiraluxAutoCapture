# Kiralux AutoCapture — User Manual

## Overview

Kiralux AutoCapture is an integrated acquisition system combining an NKT SuperK laser, Thorlabs Kiralux camera, and Yokogawa OSA optical spectrum analyzer. It supports multi-channel laser configuration, random wavelength generation, automated sweeps, and data saving.

---

## Requirements

- **Python environment**: Conda `DNN` environment
- **Dependencies**: PyQt5, numpy, matplotlib, tifffile, pyserial, thorlabs_tsi_sdk
- **Hardware**: NKT SuperK Extreme + SELECT (USB/COM), Kiralux camera (USB), Yokogawa OSA (TCP/IP)

### Launch

```bash
conda activate DNN
python main.py
```

Or use the `Run DNN` task in VS Code.

---

## Tab Reference

### 1. Hardware Test

Use this tab to verify all hardware connections before starting acquisition.

#### NKT SuperK Laser
- **Scan all NKT ports** — Scans all COM ports, auto-discovers Extreme, RF, and SuperK Select modules
- **Step 1 — Extreme ON** — Powers on the Extreme main laser at 100% emission
- **Step 2 — RF ON** — Enables the RF power module
- **Step 3 — Apply emission** — Sets a test wavelength (nm) and RF channel amplitude (0–1000 = 0–100%), begins emission
- **Turn OFF** — Shuts down Extreme + RF

> ⚠ Windows may reassign COM port numbers after USB replug. Re-scan if the port changes.

#### Camera (Thorlabs Kiralux)
- **Capture Test Frame** — Captures a single test frame with the specified exposure and gain
- Supports vmin/vmax percentile contrast adjustment

#### OSA (Yokogawa)
- **Ping OSA** — Tests the TCP connection to the OSA

---

### 2. Camera

| Parameter | Description |
|-----------|-------------|
| Exposure time | Exposure duration (ms), range 0.03–22806 |
| Gain | Sensor gain, 0–480 |
| Timeout | Frame wait timeout (ms) |
| Image format | tif / npy |
| Output directory | Path where images are saved |
| File prefix | Filename prefix for saved images |

---

### 3. NKT Laser

| Parameter | Description |
|-----------|-------------|
| COM Port | Device port (auto-matched after Scan) |
| Crystal | 0 — VIS (430–690 nm) / 1 — NIR (690–1100 nm) |
| Emission level | Emission power percentage (1–100%) |

#### Manual Multi-Peak Table
- Up to 8 channels, each with:
  - **Enabled** — Checkbox to include the channel
  - **Wavelength (nm)** — Center wavelength
  - **Amplitude (0–1000)** — RF channel amplitude (0% – 100%)
- **Set all amp = 1000** — Set all channels to full amplitude
- **Disable all** — Uncheck all channels

#### Test Emission
- **Test Emit Selected Channels** — Emits using all checked channels from the table (requires a completed Scan in Hardware Test first)
- **Turn OFF** — Shuts down the laser

---

### 4. Auto Capture Loop

#### Capture Mode

**Manual Multi-Peak**
- Uses the channel table from the NKT Laser tab
- 1 fixed configuration, repeated N times
- Use case: fixed-wavelength acquisition

**Random Multi-Peak**
- Each step generates a random multi-channel configuration
- Reproducible via Random seed

#### Random Mode Parameters

| Parameter | Description |
|-----------|-------------|
| Random seed | Random seed (same seed = same sequence) |
| N steps | Number of distinct configurations |
| Wavelength range | Wavelength bounds, e.g. 620.0 – 690.0 nm |
| Channel spacing | See below |
| Channels per step | Number of channels per step, e.g. 2–8 |
| Amplitude range | Amplitude bounds, e.g. 200–1000 |

#### Channel Spacing Modes

**Fixed grid**
- Candidate wavelengths are spaced at a fixed interval
- Example: step = 0.5 nm → 620.0, 620.5, 621.0, 621.5, ...
- Each step randomly selects N candidates from the grid
- Step supports 0.1 nm precision

**Fully random**
- Wavelengths are generated continuously (no grid)
- Adjacent channel spacing is drawn from `Uniform(min, max)`
- Example: spacing 0.1–1.0 nm → 620.3, 620.8, 621.5, 622.4, ...
- Both peak positions and spacing are random

#### Repeat & Timing

| Parameter | Description |
|-----------|-------------|
| Repeats per config | Number of captures per configuration |
| Start index offset | File numbering offset (useful for resuming runs) |
| Laser settle time | Wait time after NKT wavelength change (seconds) |

#### Total Captures
- Random mode: `N steps × repeats`
- Manual mode: `1 × repeats`

---

### 5. OSA (optional)

| Parameter | Description |
|-----------|-------------|
| Host / Port | OSA IP address and port (default: 192.168.0.1:10001) |
| Start / Stop wavelength | Sweep wavelength range |
| Resolution | Spectral resolution (nm) |
| Sampling step | Sampling interval (nm) |
| Sensitivity | Sensitivity mode |
| Average count | Number of averages |
| Reference level | Reference power level (nW) |
| Y-axis display | LIN (linear, nW) |

#### Controls
- **Scan Once** — Performs a single OSA sweep with live spectrum plot
- Supports saving CSV and PNG

---

## Auto-Exported Files

The following files are automatically generated each time Start Acquisition is pressed:

### 1. NKT Configuration CSV

**Filename format** (Random mode):
```
nkt_config_seed42_620-690nm_grid5.0nm_ch2-8_amp200-1000_em100pct.csv
```
Or (Fully random):
```
nkt_config_seed42_620-690nm_rand0.1-1.0nm_ch2-8_amp200-1000_em100pct.csv
```
Or (Manual mode):
```
nkt_config_manual.csv
```

**Contents**:
```csv
# mode=random
# seed=42
# n_steps=50
# wl_min=620.0
# wl_max=690.0
# ...
step,n_channels,wavelengths_nm,amplitudes
1,5,620.0;635.0;650.0;670.0;685.0,800;450;1000;300;650
2,3,625.0;645.0;680.0,550;900;200
```

The file header contains all parameters (seed, range, spacing, channels, amplitudes, emission, etc.). Each row records one step's wavelength and amplitude configuration.

### 2. Image Files
- Format: `{prefix}{step}_{repeat}.tif` or `.npy`
- Example: `img_loop1_1.tif`, `img_loop1_2.tif`, ...

### 3. OSA Data (if enabled)
- Spectrum plot: `osa_{step}_{repeat}.png`
- Raw data: `osa_{step}_{repeat}.csv`
- Summary log: `osa_log.csv`

---

## Typical Workflows

### First-Time Setup
1. Open the **Hardware Test** tab
2. Click **Scan all NKT ports** → confirm Extreme and RF addresses
3. Click **Step 1** → **Step 2** → **Step 3** to test laser emission
4. Click **Capture Test Frame** to verify the camera
5. Click **Ping OSA** to test the spectrometer connection

### Manual Mode Acquisition
1. Go to **NKT Laser** tab, configure channel wavelengths and amplitudes
2. Optionally click **Test Emit Selected Channels** to preview
3. Go to **Auto Capture Loop**, select **Manual Multi-Peak**
4. Set repeats and settle time
5. Click **Start Acquisition**

### Random Mode Acquisition
1. Go to **Auto Capture Loop**, select **Random Multi-Peak**
2. Set seed, N steps, wavelength range
3. Choose **Fixed grid** or **Fully random** spacing mode
4. Set channels per step and amplitude range
5. Click **Start Acquisition**
6. The NKT config CSV is automatically saved to the output directory

### OSA-Only Mode
- In the **Camera** tab, check **OSA only (skip camera)**
- Runs NKT + OSA only, no image capture

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| NKT shows "not connected" | Re-scan, check USB cable, close other NKT software |
| NKT does not emit | Ensure Step 1 → Step 2 → Step 3 are completed in order |
| COM port changed | Windows reassigns after replug — re-scan |
| Camera timeout | Increase timeout_ms, check camera USB connection |
| OSA connection failed | Check IP (default 192.168.0.1), Ethernet cable, firewall |
| OSA data looks wrong | Confirm Y-axis is set to LIN mode, check resolution and sampling |

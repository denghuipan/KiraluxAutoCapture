# Kiralux AutoCapture — User Manual

## Launch

```bash
pip install -r requirements.txt
python main.py
```

## Tabs

### 1. Hardware Test

Verify all hardware before acquisition.

**NKT Laser**
- **Scan all NKT ports** — auto-discovers Extreme, RF, SuperK Select on all COM ports
- **Step 1** → Extreme ON (100% emission)
- **Step 2** → RF ON (zeros all 8 channels)
- **Step 3** → Set wavelength (400–1100 nm) + RF amplitude (0–100%), apply emission
- **Turn OFF** — safe shutdown
- ⚠ Windows may reassign COM ports after USB replug — re-scan

**Camera**
- **Capture test frame** with exposure/gain, live preview with contrast controls

**Power Meter (PM100D)**
- **Scan VISA resources** — auto-discovers USB power meters
- **Read power** — single-shot measurement (W + dBm)
- **Zero (dark)** — SCPI offset calibration (cover sensor first)
- **Set wavelength** — correction wavelength (400–2000 nm)

**OSA**
- **Ping OSA** — TCP connection test

---

### 2. Camera

| Parameter | Range |
|-----------|-------|
| Exposure | 0.03 – 22806 ms ("Max" button, "Always max" toggle) |
| Gain | 0 – 480 (0 – 48 dB) |
| Timeout | 100 – 60000 ms (auto-enforced > exposure) |

**ROI**: Full frame (4096×2160) or custom (x1, y1, x2, y2)

**Output**: Directory + prefix, format TIFF / NPY / DAT

**Auto ROI Crop** (optional)
- Saves cropped TIFF + PNG preview per frame
- Max-sum sliding window algorithm
- Configurable signal window (W×H), outer crop (W×H), output subdir
- PNG contrast stretch (1–99%)

**Image H5 Export** (optional)
- Appends cropped frames to HDF5 with paired labels (`roundXX_loopYY_j`)
- Optional vmin/vmax contrast preprocessing
- Gzip compressed

---

### 3. NKT Laser

- **COM port** selector with refresh
- **Crystal**: 0 = VIS (430–690 nm), 1 = NIR (690–1100 nm)
- **Emission level**: 1–100%

**Manual Multi-Peak Table** (up to 8 channels)
- Each row: Enabled checkbox + Wavelength (nm) + Amplitude (0–1000)
- **Set all amp = 1000** / **Disable all** buttons
- **Test Emit Selected Channels** / **Turn OFF**

---

### 4. Auto Capture Loop

#### Training Strategy
- Up to **50 rounds**, each with independent capture mode
- Prev/Next navigation, save per-round config, status tracking (✓ saved)

#### Capture Modes

| Mode | Description |
|------|-------------|
| **Random Multi-Peak** | Seed, N steps, wavelength range, spacing (fixed grid or fully random), channels per step, amplitude range |
| **Manual Multi-Peak** | Uses NKT tab table, 1 config × repeats |
| **Single Peak Scan** | Wavelength sweep (start → end, step ≥ 0.1 nm), single RF amplitude |
| **Broadband** | 8 channels (~10 nm span), center wavelength (fixed or random), amplitude mode: equal / random / manual per-channel |

#### Repeat & Timing
- Repeats per config (1–1000), start index offset
- Laser settle time (0–10 s), inter-frame delay (0–60 s)

#### Options
- **Enable OSA in loop** — capture spectrum at each step
- **OSA only (skip camera)** — NKT + OSA, no images

---

### 5. OSA

| Parameter | Range |
|-----------|-------|
| Host / Port | IP:10001 (default: 192.168.0.1) |
| Wavelength | 400 – 2000 nm |
| Resolution | 0.02 – 5.0 nm |
| Sampling step | 0.001 – 10.0 nm |
| Sensitivity | norm / mid / high1 / high2 / high3 |
| Averages | 1 – 1000 |
| Smoothing | OFF / 2 / 4 / 8 / 16 / 32 |

**Scan Once** — single sweep with live spectrum plot

**H5 Export** (optional)
- Savitzky-Golay smoothing + downsample to N points (2–5000)
- Filter by wavelength range before reduction

---

### 6. Test Data

RF power servo to reach target output power levels, with automatic image capture.

**Laser & Targets**
- **Wavelength**: comma/semicolon separated list (or "From Loop Tab" to sync)
- **Target power (dBm)**: comma-separated (e.g. -20, -30, -40)
- **Coupling efficiency**: mantissa × 10^exponent
- **Power tolerance**: dB threshold for matching
- **PM hint**: shows expected PM reading in W

**RF Control**
- **RF floor/ceiling**: min/max amplitude bounds
- **Servo algorithms**: linear ramp or binary search
- **Delay per RF step** (ms), settle after trigger

**Power Meter**
- Backend: PM100D (USB/VISA) or Simulated
- VISA resource scan + text input

**Camera**
- Use Camera tab settings or override exposure/gain
- Repeats per step (filename gets `_rep1`, `_rep2` suffix)

**Live Power Monitor**
- Toggle "Show Live Power" to stream PM readings before test
- Real-time chart with target band, color-coded phases
- Unit selector: dBm or auto-scaled W (pW/nW/µW/mW/W)

**Output**
- Log CSV: timestamped entries with wavelength, target, PM reading, RF, filename, status
- Per-step PM trace CSV with phase labels
- Auto ROI crop applied (if enabled in Camera tab)

---

## Settings

- **Theme**: Dark (Catppuccin Mocha) / Light (Catppuccin Latte)
- **Font**: family + size (8–24 pt), live preview
- Persisted via QSettings (Windows registry)

---

## Output Files

| File | Description |
|------|-------------|
| `{prefix}{step}_{repeat}.tif` | Captured image |
| `nkt_config_*.csv` | NKT step configs (auto-generated with descriptive name) |
| `osa_{step}_{repeat}.csv` | OSA raw data |
| `osa_{step}_{repeat}.png` | OSA spectrum plot |
| `osa_log.csv` | OSA summary log |
| `images.h5` | Paired image dataset (optional) |
| `osa_spectra.h5` | Paired OSA H5 dataset (optional) |
| `test_data_log.csv` | Test data run log |
| `pm_trace_step*.csv` | Per-step power telemetry |
| `cropped/` | Auto-cropped TIFFs + PNG previews |

---

## Typical Workflow

1. **Hardware Test** → verify all devices (scan NKT → laser ON → test frame → ping OSA/PM)
2. **Camera** → set ROI, output path, enable H5 export if needed
3. **NKT Laser** → configure channels (for Manual mode)
4. **Auto Loop** → select mode, set rounds/params, **Start Acquisition**
5. **Test Data** (optional) → set targets, run RF servo to reach power levels

# Kiralux AutoCapture — Quick Manual

## Launch

```bash
pip install -r requirements.txt
python main.py
```

## Tabs

### 1. Hardware Test

Verify all hardware before acquisition.

- **Scan all NKT ports** — auto-discovers Extreme, RF, SuperK Select on COM ports
- **Step 1 → Step 2 → Step 3** — laser bring-up sequence
- **Turn OFF** — safe shutdown
- **Capture test frame** — camera test with live preview
- **Read PM power** — PM100D measurement + VISA scan
- **Zero (dark)** — PM dark calibration (cover sensor)
- **Ping OSA** — TCP connection test

### 2. Camera

| Parameter | Range |
|-----------|-------|
| Exposure | 0.03–22806 ms ("Max" button, "Always max" toggle) |
| Gain | 0–480 |
| Timeout | 100–60000 ms (auto > exposure) |

**ROI**: Full frame (4096×2160) or custom (x1,y1,x2,y2)

**Output**: Directory + prefix, format TIFF / NPY / DAT

**Auto ROI Crop**: max-sum sliding window → cropped TIFF + PNG per frame. Configurable signal window, outer crop, output subdir, PNG contrast stretch

**Image H5 Export**: append cropped frames to HDF5 with labels (`roundXX_loopYY_j`), optional vmin/vmax contrast preprocessing

### 3. NKT Laser

- **COM port** selector + refresh
- **Crystal**: 0 = VIS (430–690 nm), 1 = NIR (690–1100 nm)
- **Emission**: 1–100%
- **8-channel table**: Enabled + Wavelength (nm) + Amplitude (0–1000)
- **Test Emit** / **Turn OFF** buttons

### 4. Auto Capture Loop

**Training Strategy**: up to 50 rounds, each with independent mode. Prev/Next navigation, save per-round config. Inline test set: reproducible test subset after each round.

**5 Capture Modes**:

| Mode | Description |
|------|-------------|
| **Random** | Seed, N steps, wavelength range, spacing (fixed grid or fully random), channels per step, amplitude range |
| **Manual** | Uses NKT tab table, 1 config × repeats |
| **Single Peak Scan** | Wavelength sweep (start → end, step ≥ 0.1 nm) |
| **Broadband** | 8ch, configurable span/center/spacing/amplitude (fixed or random) |
| **Absorption Peak** | 8ch with baseline amplitude + configurable absorption dips (baseline amplitude with reduced dips for selected channels) |

**Timing**: repeats per config, start index offset, laser settle time, inter-frame delay

### 5. Test Data

RF power servo to reach target output power levels, then capture images.

- **Wavelength**: comma-separated list, or "From Loop Tab" (syncs with current loop config)
- **Target power (dBm)**: comma-separated (e.g. -20, -30, -40)
- **Coupling efficiency**: mantissa × 10^exponent
- **RF servo**: linear ramp or binary search, RF floor/ceiling bounds
- **Power Meter**: PM100D (USB/VISA) or Simulated (dev)
- **Live Power Monitor**: stream PM readings before test (no laser/RF interaction)
- **Real-time chart**: power vs time with target band, color-coded phases (adjust/triggered/settle/verify/live)
- **Repeats per step**: multiple frames at locked power
- **Bright Field Pre-capture**: multi-exposure images at full RF before servo loop
- **Output**: log CSV + per-step PM trace CSV
- Auto ROI crop applied (if enabled in Camera tab)

### 6. OSA

| Parameter | Range |
|-----------|-------|
| Host / Port | IP:10001 (default: 192.168.0.1) |
| Wavelength | 400–2000 nm |
| Resolution | 0.02–5.0 nm |
| Sensitivity | norm / mid / high1 / high2 / high3 |
| Smoothing | OFF / 2 / 4 / 8 / 16 / 32 |

**Scan Once**: single sweep with live spectrum plot. **Enable OSA in loop**: capture spectrum at each loop step. **Only OSA**: NKT + OSA, no camera.

**H5 Export**: Savitzky-Golay smoothing + downsample to N points, filter by wavelength range

## Settings

- **Theme**: Dark (Catppuccin Mocha) / Light (Catppuccin Latte)
- **Font**: family + size (8–24 pt), live preview

## Output Files

| File | Description |
|------|-------------|
| `{prefix}{step}_{repeat}.tif` | Captured image |
| `nkt_config_*.csv` | NKT step configs (auto-generated) |
| `images.h5` | Paired image dataset |
| `osa_spectra.h5` | Paired OSA spectra |
| `osa_*.csv/.png` | OSA raw data + plot |
| `test_data_log.csv` | Test data run log |
| `pm_trace_step*.csv` | Per-step power telemetry |
| `cropped/` | Auto-cropped TIFFs + PNG |
| `bright/` | Bright field pre-capture images |

# Kiralux AutoCapture — Quick Manual

## Launch

```bash
pip install -r requirements.txt
python main.py
```

## Tabs

| Tab | Description |
|-----|-------------|
| **Hardware Test** | Verify connections: scan NKT ports, test laser (Extreme → RF → Emission), capture test frame, ping OSA |
| **Camera** | Set ROI, exposure (0.03–22806 ms), gain (0–480), output dir, format (tif/npy) |
| **NKT Laser** | Select COM port, crystal (VIS/NIR), emission level. Manual multi-peak table (up to 8 channels with wavelength + amplitude) |
| **Auto Loop** | **Manual mode**: fixed config × repeats. **Random mode**: auto-generate N steps with seed, wavelength range, channel spacing (fixed grid or fully random), amplitude range |
| **OSA** | Set IP/port, wavelength range, resolution, sensitivity. Single scan with live plot |
| **Test Data** | Replay saved acquisitions |

## Workflow

1. **Hardware Test** → verify all devices
2. **Camera** → set ROI and output path
3. **NKT Laser** → configure channels (for manual mode)
4. **Auto Loop** → choose mode, set parameters, **Start Acquisition**

## Output Files

- **Images**: `{prefix}{step}_{repeat}.tif`
- **NKT config**: `nkt_config_*.csv`
- **OSA**: `osa_*.csv` / `osa_*.png` + `osa_log.csv`

# Kiralux AutoCapture — 快速手册

## 启动

```bash
pip install -r requirements.txt
python main.py
```

## 标签页

| 标签 | 说明 |
|------|------|
| **Hardware Test** | 测试连接：扫描 NKT 端口、测试激光（Extreme → RF → Emission）、拍摄测试帧、Ping OSA |
| **Camera** | 设置 ROI、曝光（0.03–22806 ms）、增益（0–480）、输出路径、格式（tif/npy） |
| **NKT Laser** | 选择 COM 口、晶体（VIS/NIR）、发射功率。手动多峰表（最多 8 通道，波长 + 振幅） |
| **Auto Loop** | **手动模式**：固定配置 × 重复次数。**随机模式**：用种子自动生成 N 步，设置波长范围、通道间隔（固定网格/全随机）、振幅范围 |
| **OSA** | 设置 IP/端口、波长范围、分辨率、灵敏度。单次扫描 + 实时绘图 |
| **Test Data** | 回放已保存的采集数据 |

## 工作流程

1. **Hardware Test** → 确认所有设备连接正常
2. **Camera** → 设置 ROI 和输出路径
3. **NKT Laser** → 配置通道（手动模式）
4. **Auto Loop** → 选择模式、设置参数、**Start Acquisition**

## 输出文件

- **图像**: `{prefix}{step}_{repeat}.tif`
- **NKT 配置**: `nkt_config_*.csv`
- **OSA 数据**: `osa_*.csv` / `osa_*.png` + `osa_log.csv`

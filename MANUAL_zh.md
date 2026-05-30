# Kiralux AutoCapture — 用户手册

## 启动

```bash
pip install -r requirements.txt
python main.py
```

## 标签页

### 1. Hardware Test（硬件测试）

- **Scan all NKT ports** — 自动扫描所有 COM 口，发现 Extreme、RF、SuperK Select
- **Step 1 → Step 2 → Step 3** — 激光启动流程
- **Turn OFF** — 安全关闭
- **Capture test frame** — 相机测试 + 实时预览
- **Read PM power** — 功率计测量 + VISA 扫描
- **Zero (dark)** — 暗电流校准（盖住传感器）
- **Ping OSA** — TCP 连接测试

### 2. Camera（相机）

| 参数 | 范围 |
|------|------|
| Exposure | 0.03–22806 ms（"Max" 按钮、"Always max" 开关） |
| Gain | 0–480 |
| Timeout | 100–60000 ms（自动 > 曝光时间） |

**ROI**: 全帧（4096×2160）或自定义

**输出**: 目录 + 前缀，格式 TIFF / NPY / DAT

**Auto ROI Crop**: 最大和值滑动窗口算法 → 每帧输出裁剪 TIFF + PNG

**Image H5 导出**: 裁剪帧追加到 HDF5，带标签，可选对比度预处理

### 3. NKT Laser（激光）

- COM 口选择 + 刷新、Crystal (VIS/NIR)、Emission 1–100%
- 8 通道表：启用 + 波长 (nm) + 振幅 (0–1000)
- 测试发射 / 关闭按钮

### 4. Auto Capture Loop（自动循环）

**训练策略**: 最多 50 轮，每轮独立配置。前/后导航，保存/恢复每轮配置。内联测试集：每轮后自动采集可复现的测试子集。

**5 种采集模式**:

| 模式 | 说明 |
|------|------|
| **Random** | 随机种子、N 步、波长范围、通道间隔（固定网格/全随机） |
| **Manual** | 使用 NKT 标签页配置 |
| **Single Peak Scan** | 波长扫描（起始 → 终止，步长 ≥ 0.1 nm） |
| **Broadband** | 8 通道，可配置跨度/中心/间隔/振幅（固定或随机） |
| **Absorption Peak** | 8 通道，基线振幅 + 可配置吸收凹陷（指定通道降低振幅） |

### 5. Test Data（测试数据）

RF 功率伺服控制自动到达目标功率并采集图像。

- **波长**: 逗号分隔列表，或 "From Loop Tab" 同步 Loop 标签页
- **目标功率 (dBm)**: 逗号分隔（如 -20, -30, -40）
- **耦合效率**: 尾数 × 10^指数
- **RF 伺服**: 线性扫描 或 二分查找
- **功率计**: PM100D (USB/VISA) 或 模拟
- **实时功率监测**: 测试前持续读取功率（不碰激光/RF）
- **实时图表**: 功率 vs 时间，颜色编码阶段
- **每步重复**: 锁定功率下多次采集
- **Bright Field 预采集**: 伺服循环前以全功率多曝光采集
- **输出**: 日志 CSV + 每步功率追踪 CSV

### 6. OSA（光谱仪）

| 参数 | 范围 |
|------|------|
| Host / Port | IP:10001（默认: 192.168.0.1） |
| 波长 | 400–2000 nm |
| 分辨率 | 0.02–5.0 nm |
| 平滑 | OFF / 2 / 4 / 8 / 16 / 32 |

**Scan Once**: 单次扫描 + 实时光谱图。**Enable OSA in loop**: 每步采集光谱。**Only OSA**: 仅 NKT + OSA。**H5 导出**: Savitzky-Golay 平滑 + 降采样

## 设置

- **主题**: Dark / Light（Catppuccin）
- **字体**: 字族 + 大小（8–24 pt），实时预览

## 输出文件

| 文件 | 说明 |
|------|------|
| `{prefix}{step}_{repeat}.tif` | 采集图像 |
| `nkt_config_*.csv` | NKT 步进配置 |
| `images.h5` | 配对图像数据集 |
| `osa_spectra.h5` | 配对 OSA 光谱数据集 |
| `osa_*.csv/.png` | OSA 原始数据 + 图 |
| `test_data_log.csv` | 测试数据日志 |
| `pm_trace_step*.csv` | 每步功率遥测 |
| `cropped/` | 自动裁剪 TIFF + PNG |
| `bright/` | Bright Field 预采集图像 |

# Kiralux AutoCapture — 用户手册

## 概述

Kiralux AutoCapture 是一个集成 NKT SuperK 激光器、Thorlabs Kiralux 相机和 Yokogawa OSA 光谱仪的自动采集系统。支持多通道激光配置、随机波长生成、自动扫描和数据保存。

---

## 环境要求

- **Python 环境**: Conda `DNN` 环境
- **依赖**: PyQt5, numpy, matplotlib, tifffile, pyserial, thorlabs_tsi_sdk
- **硬件**: NKT SuperK Extreme + SELECT (USB/COM), Kiralux 相机 (USB), Yokogawa OSA (TCP/IP)

### 启动方式

```bash
conda activate DNN
python main.py
```

或使用 VS Code 中的 `Run DNN` 任务。

---

## Tab 页说明

### 1. Hardware Test（硬件测试）

首次使用时在此页面测试所有硬件连接。

#### NKT SuperK Laser
- **Scan all NKT ports** — 扫描所有 COM 口，自动发现 Extreme、RF 和 SuperK Select 模块
- **Step 1 — Extreme ON** — 打开 Extreme 主激光，emission 100%
- **Step 2 — RF ON** — 打开 RF 功率模块
- **Step 3 — Apply emission** — 设置测试波长（nm）和 RF 通道振幅（0–1000 = 0–100%），开始发射
- **Turn OFF** — 关闭 Extreme + RF

> ⚠ Windows 可能在拔插 USB 后重新分配 COM 口。重新扫描即可。

#### Camera (Thorlabs Kiralux)
- **Capture Test Frame** — 使用指定曝光时间和增益拍摄一张测试图
- 支持 vmin/vmax 百分比调节对比度

#### OSA (Yokogawa)
- **Ping OSA** — 测试 TCP 连接

---

### 2. Camera（相机设置）

| 参数 | 说明 |
|------|------|
| Exposure time | 曝光时间（ms），范围 0.03–22806 |
| Gain | 增益 0–480 |
| Timeout | 帧等待超时（ms） |
| Image format | tif / npy |
| Output directory | 图像保存路径 |
| File prefix | 文件名前缀 |

---

### 3. NKT Laser（NKT 激光设置）

| 参数 | 说明 |
|------|------|
| COM Port | 设备端口（Scan 后自动匹配） |
| Crystal | 0 — VIS (430–690 nm) / 1 — NIR (690–1100 nm) |
| Emission level | 发射功率百分比（1–100%） |

#### Manual Multi-Peak 配置表
- 最多 8 个通道，每个通道可设置：
  - **Enabled** — 勾选启用
  - **Wavelength (nm)** — 波长
  - **Amplitude (0–1000)** — RF 通道振幅（0% – 100%）
- **Set all amp = 1000** — 所有通道满振幅
- **Disable all** — 取消全部勾选

#### 测试发射
- **Test Emit Selected Channels** — 使用表中勾选的通道进行测试发射（需先在 Hardware Test 完成 Scan）
- **Turn OFF** — 关闭激光

---

### 4. Auto Capture Loop（自动采集循环）

#### Capture Mode（采集模式）

**Manual Multi-Peak（手动模式）**
- 使用 NKT Laser 页的通道表配置
- 只有 1 组固定配置，重复 N 次
- 适用于：固定波长采集

**Random Multi-Peak（随机模式）**
- 每一步自动生成随机多通道配置
- 可复现（使用 Random seed）

#### Random 模式参数

| 参数 | 说明 |
|------|------|
| Random seed | 随机种子（相同种子 = 相同序列） |
| N steps | 不同配置的数量 |
| Wavelength range | 波长范围，如 620.0 – 690.0 nm |
| Channel spacing | 见下方 |
| Channels per step | 每步通道数范围，如 2–8 |
| Amplitude range | 振幅范围，如 200–1000 |

#### Channel Spacing（通道间隔模式）

**Fixed grid（固定网格）**
- 候选波长按固定步长排列
- 例如：step=0.5nm → 620.0, 620.5, 621.0, 621.5, ...
- 每步从候选中随机选 N 个
- step 支持 0.1nm 精度

**Fully random（全随机）**
- 波长完全随机生成
- 相邻通道间距从 `Uniform(min, max)` 随机抽取
- 例如：spacing 0.1–1.0nm → 620.3, 620.8, 621.5, 622.4, ...
- 波峰位置随机 + 间隔随机 = 全随机

#### Repeat & Timing

| 参数 | 说明 |
|------|------|
| Repeats per config | 每组配置重复采集次数 |
| Start index offset | 文件编号起始偏移（续跑时有用） |
| Laser settle time | NKT 切换波长后的等待时间（秒） |

#### 总采集数
- Random: `N steps × repeats`
- Manual: `1 × repeats`

---

### 5. OSA (optional)（光谱仪设置）

| 参数 | 说明 |
|------|------|
| Host / Port | OSA 的 IP 和端口（默认 192.168.0.1:10001） |
| Start / Stop wavelength | 扫描波长范围 |
| Resolution | 分辨率（nm） |
| Sampling step | 采样步长（nm） |
| Sensitivity | 灵敏度模式 |
| Average count | 平均次数 |
| Reference level | 参考电平（nW） |
| Y-axis display | LIN（线性 nW） |

#### 按钮
- **Scan Once** — 手动执行一次 OSA 扫描，结果在右侧实时绘图
- 支持保存 CSV 和 PNG

---

## 自动导出文件

每次 Start Acquisition 时自动生成以下文件：

### 1. NKT 配置 CSV

**文件名格式**（Random 模式）：
```
nkt_config_seed42_620-690nm_grid5.0nm_ch2-8_amp200-1000_em100pct.csv
```
或（Fully random）：
```
nkt_config_seed42_620-690nm_rand0.1-1.0nm_ch2-8_amp200-1000_em100pct.csv
```
或（Manual 模式）：
```
nkt_config_manual.csv
```

**内容**：
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

### 2. 图像文件
- 格式：`{prefix}{step}_{repeat}.tif` 或 `.npy`
- 例如：`img_loop1_1.tif`, `img_loop1_2.tif`, ...

### 3. OSA 数据（如启用）
- PNG 图：`osa_{step}_{repeat}.png`
- CSV 数据：`osa_{step}_{repeat}.csv`
- 汇总日志：`osa_log.csv`

---

## 典型工作流

### 首次启动
1. 打开 **Hardware Test**
2. 点 **Scan all NKT ports** → 确认 Extreme、RF 地址
3. 点 **Step 1** → **Step 2** → **Step 3** 测试激光发射
4. 点 **Capture Test Frame** 测试相机
5. 点 **Ping OSA** 测试光谱仪连接

### 手动模式采集
1. 在 **NKT Laser** 页设置通道波长和振幅
2. 可点 **Test Emit Selected Channels** 预览发射
3. 在 **Auto Capture Loop** 选 **Manual Multi-Peak**
4. 设置 repeats 和 settle time
5. 点 **Start Acquisition**

### 随机模式采集
1. 在 **Auto Capture Loop** 选 **Random Multi-Peak**
2. 设置 seed、N steps、波长范围
3. 选择 **Fixed grid** 或 **Fully random** 间隔模式
4. 设置通道数范围、振幅范围
5. 点 **Start Acquisition**
6. 配置 CSV 自动保存到输出目录

### Only OSA 模式
- 在 **Camera** 页勾选 **OSA only (skip camera)**
- 仅用 NKT + OSA，不拍照

---

## 故障排查

| 问题 | 解决方法 |
|------|----------|
| NKT 显示 "not connected" | 重新 Scan，检查 USB 线，关闭其他 NKT 软件 |
| NKT 不发射 | 确认 Step 1 → Step 2 → Step 3 依次完成 |
| COM 口变了 | Windows 拔插后重新分配，重新 Scan |
| Camera timeout | 增大 timeout_ms，检查相机 USB 连接 |
| OSA 连接失败 | 检查 IP (默认 192.168.0.1)，网线，防火墙 |
| OSA 数据异常 | 确认 Y-axis 为 LIN 模式，检查 resolution 和 sampling |

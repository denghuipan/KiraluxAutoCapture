# Kiralux AutoCapture — 用户手册

## 启动

```bash
pip install -r requirements.txt
python main.py
```

## 标签页

### 1. Hardware Test（硬件测试）

采集前验证所有硬件连接。

**NKT 激光**
- **Scan all NKT ports** — 自动扫描所有 COM 口，发现 Extreme、RF、SuperK Select
- **Step 1** → Extreme ON（100% emission）
- **Step 2** → RF ON（清空全部 8 通道）
- **Step 3** → 设置波长（400–1100 nm）+ RF 振幅（0–100%），开始发射
- **Turn OFF** — 安全关闭
- ⚠ Windows 拔插 USB 后可能重新分配 COM 口 — 重新扫描即可

**相机**
- **Capture test frame** — 用指定曝光/增益拍摄测试帧，实时预览 + 对比度调节

**功率计（PM100D）**
- **Scan VISA resources** — 自动发现 USB 功率计
- **Read power** — 单次功率测量（W + dBm）
- **Zero (dark)** — 暗电流校准（先盖住传感器）
- **Set wavelength** — 校正波长（400–2000 nm）

**OSA**
- **Ping OSA** — TCP 连接测试

---

### 2. Camera（相机）

| 参数 | 范围 |
|------|------|
| Exposure | 0.03 – 22806 ms（"Max" 按钮、"Always max" 开关） |
| Gain | 0 – 480（0 – 48 dB） |
| Timeout | 100 – 60000 ms（自动强制 > 曝光时间） |

**ROI**: 全帧（4096×2160）或自定义（x1, y1, x2, y2）

**输出**: 目录 + 前缀，格式 TIFF / NPY / DAT

**Auto ROI Crop**（可选）
- 每帧自动裁剪并保存 TIFF + PNG 预览
- 最大和值滑动窗口算法
- 可配置信号窗口（W×H）、外裁（W×H）、输出子目录
- PNG 对比度拉伸（1–99%）

**Image H5 导出**（可选）
- 将裁剪帧追加到 HDF5，带配对标签（`roundXX_loopYY_j`）
- 可选 vmin/vmax 对比度预处理
- gzip 压缩

---

### 3. NKT Laser（激光）

- **COM 口** 选择器 + 刷新按钮
- **Crystal**: 0 = VIS (430–690 nm), 1 = NIR (690–1100 nm)
- **Emission**: 1–100%

**Manual Multi-Peak 表**（最多 8 通道）
- 每行：启用复选框 + 波长 (nm) + 振幅 (0–1000)
- **Set all amp = 1000** / **Disable all** 按钮
- **Test Emit Selected Channels** / **Turn OFF**

---

### 4. Auto Capture Loop（自动循环）

#### 训练策略
- 最多 **50 轮**，每轮独立配置采集模式
- 前/后导航，保存每轮配置，状态标记（✓ 已保存）

#### 采集模式

| 模式 | 说明 |
|------|------|
| **Random Multi-Peak** | 随机种子、N 步、波长范围、通道间隔（固定网格/全随机）、每步通道数、振幅范围 |
| **Manual Multi-Peak** | 使用 NKT 标签页配置，1 组配置 × 重复次数 |
| **Single Peak Scan** | 波长扫描（起始 → 终止，步长 ≥ 0.1 nm），单 RF 振幅 |
| **Broadband** | 8 通道（~10 nm 跨度），中心波长（固定/随机），振幅模式：均等/随机/逐通道手动 |

#### 重复 & 时序
- 每组重复次数（1–1000）、起始编号偏移
- 激光稳定时间（0–10 s）、帧间延迟（0–60 s）

#### 选项
- **Enable OSA in loop** — 每步采集光谱
- **OSA only (skip camera)** — 仅 NKT + OSA，不拍照

---

### 5. OSA（光谱仪）

| 参数 | 范围 |
|------|------|
| Host / Port | IP:10001（默认: 192.168.0.1） |
| 波长 | 400 – 2000 nm |
| 分辨率 | 0.02 – 5.0 nm |
| 采样步长 | 0.001 – 10.0 nm |
| 灵敏度 | norm / mid / high1 / high2 / high3 |
| 平均次数 | 1 – 1000 |
| 平滑 | OFF / 2 / 4 / 8 / 16 / 32 |

**Scan Once** — 单次扫描 + 实时光谱图

**H5 导出**（可选）
- Savitzky-Golay 平滑 + 降采样到 N 个点（2–5000）
- 降维前可过滤波长范围

---

### 6. Test Data（测试数据）

RF 功率伺服控制，自动到达目标输出功率并采集图像。

**激光 & 目标**
- **波长**: 逗号/分号分隔列表（或 "From Loop Tab" 同步 Loop 标签页配置）
- **目标功率 (dBm)**: 逗号分隔（如 -20, -30, -40）
- **耦合效率**: 尾数 × 10^指数
- **功率容差**: 匹配目标的 dB 阈值
- **PM 提示**: 显示预期的功率计读数

**RF 控制**
- **RF 下限/上限**: 最小/最大振幅
- **伺服算法**: 线性扫描 或 二分查找
- **每步 RF 延迟**（ms）、触发后稳定时间

**功率计**
- 后端: PM100D (USB/VISA) 或 模拟
- VISA 端口扫描 + 文本输入

**相机**
- 使用 Camera 标签页设置 或 独立覆盖曝光/增益
- 每步重复次数（文件名带 `_rep1`、`rep2` 后缀）

**实时功率监测**
- 点击 "Show Live Power" 在测试前持续读取功率
- 实时图表：目标带 + 颜色编码阶段
- 单位选择: dBm 或 自动缩放 W (pW/nW/µW/mW/W)

**输出**
- Log CSV: 时间戳记录，含波长、目标、PM 读数、RF、文件名、状态
- 每步 PM 追踪 CSV，带阶段标签
- 自动 ROI 裁剪（如 Camera 标签页已启用）

---

## 设置

- **主题**: Dark (Catppuccin Mocha) / Light (Catppuccin Latte)
- **字体**: 字族 + 大小（8–24 pt），实时预览
- 通过 QSettings 持久化（Windows 注册表）

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `{prefix}{step}_{repeat}.tif` | 采集图像 |
| `nkt_config_*.csv` | NKT 步进配置（自动生成描述性文件名） |
| `osa_{step}_{repeat}.csv` | OSA 原始数据 |
| `osa_{step}_{repeat}.png` | OSA 光谱图 |
| `osa_log.csv` | OSA 汇总日志 |
| `images.h5` | 配对图像数据集（可选） |
| `osa_spectra.h5` | 配对 OSA H5 数据集（可选） |
| `test_data_log.csv` | 测试数据运行日志 |
| `pm_trace_step*.csv` | 每步功率遥测数据 |
| `cropped/` | 自动裁剪 TIFF + PNG 预览 |

---

## 典型工作流

1. **Hardware Test** → 验证所有设备（扫描 NKT → 激光 ON → 测试帧 → 测试 OSA/PM）
2. **Camera** → 设置 ROI、输出路径、如需则启用 H5 导出
3. **NKT Laser** → 配置通道（手动模式）
4. **Auto Loop** → 选择模式、设置轮次/参数、**Start Acquisition**
5. **Test Data**（可选）→ 设置目标、运行 RF 伺服到达目标功率

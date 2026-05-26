# Kiralux AutoCapture

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue)](https://www.python.org/)
[![PyQt5](https://img.shields.io/badge/UI-PyQt5-green)](https://www.riverbankcomputing.com/software/pyqt/)
[![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey)](https://github.com/denghuipan/KiraluxAutoCapture)

**Kiralux AutoCapture** 是一个集成化的自动图像采集系统，用于光学实验中的自动化数据采集与控制。支持 Thorlabs Kiralux 相机、NKT SuperK 激光器、Yokogawa OSA 光谱仪和功率计等硬件设备的协同控制与自动化扫描。

---

## 功能概览

| 功能模块 | 说明 |
|---------|------|
| **📷 相机控制** | Thorlabs Kiralux 系列相机控制，支持 ROI 设置、曝光/增益调节、连续采集与图像保存 |
| **🔦 激光控制** | NKT SuperK Extreme + SELECT 激光器控制，支持多通道波长配置、RF 功率调节、随机波长生成 |
| **📊 光谱分析** | Yokogawa OSA 光谱仪 TCP/IP 控制，支持光谱采集、降维平滑处理 |
| **⚡ 功率测量** | 功率计数据采集与实时监控 |
| **🔄 自动扫描循环** | 支持多波长循环扫描、多 ROI 采集、自动曝光调节、数据自动保存（HDF5/TIFF/CSV） |
| **🛠 硬件测试** | 集成硬件测试面板，快速诊断所有设备连接状态 |
| **📁 回放分析** | 测试数据回放与后处理功能 |

---

## 硬件兼容性

| 设备 | 型号 | 接口 | 状态 |
|------|------|------|------|
| Thorlabs Kiralux 相机 | CS505MUP / 全系列 | USB 3.0 (thorlabs_tsi_sdk) | ✅ 已支持 |
| NKT SuperK 激光器 | SuperK Extreme + SELECT | USB/COM (串口) | ✅ 已支持 |
| NKT RF 功率模块 | RF 模块 | USB/COM (串口) | ✅ 已支持 |
| Yokogawa OSA | AQ6370D 系列 | TCP/IP | ✅ 已支持 |
| 功率计 | 支持 VISA/PyVISA 的设备 | USB/TCP | ✅ 已支持 |

---

## 环境要求

- **操作系统**: Windows 10/11（需 thorlabs_tsi_sdk 原生 DLL 支持）
- **Python**: 3.9+
- **推荐环境**: Conda `DNN` 环境

### 依赖库

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

## 快速开始

### 1. 安装依赖

```bash
conda activate DNN
pip install -r requirements.txt
```

### 2. 运行程序

```bash
python main.py
```

或在 VS Code 中使用 `Run DNN` 任务。

### 3. 打包为可执行文件

```bat
build_exe.bat
```

输出路径：`dist_release\KiraluxAutoCapture_v2\KiraluxAutoCapture_v2.exe`

---

## 项目结构

```
autocapture/
├── main.py                      # 程序入口
├── requirements.txt             # Python 依赖
├── KiraluxAutoCapture.spec      # PyInstaller 打包配置
├── build_exe.bat                # 打包脚本
├── .gitignore
├── MANUAL_en.md                 # 英文用户手册
├── MANUAL_zh.md                 # 中文用户手册
│
├── core/                        # 核心业务逻辑
│   ├── app_settings.py          # 应用设置 & 主题配置（暗色/亮色）
│   ├── camera_support.py        # Kiralux 相机 SDK 封装
│   ├── h5_store.py              # HDF5 数据存储
│   ├── hw_tester.py             # 硬件诊断工具
│   ├── image_contrast.py        # 图像对比度调整
│   ├── loop_runner.py           # 自动采集循环引擎（QThread）
│   ├── nkt_support.py           # NKT 激光器 SDK 封装
│   ├── nkt_thread.py            # NKT 专用线程（避免 IBHandler 冲突）
│   ├── osa_reduce.py            # OSA 光谱降维/平滑
│   ├── pm_meter.py              # 功率计控制
│   ├── power_math.py            # 功率计算工具
│   ├── rf_power_control.py      # RF 功率控制
│   ├── roi_postprocess.py       # ROI 后处理
│   ├── sample_label.py          # 样本标签管理
│   └── test_data_runner.py      # 测试数据回放引擎
│
├── ui/                          # 图形界面
│   ├── main_window.py           # 主窗口
│   ├── settings_dialog.py       # 设置对话框
│   ├── style_helpers.py         # 样式辅助
│   ├── tab_camera.py            # 相机控制标签页
│   ├── tab_hardware_test.py     # 硬件测试标签页
│   ├── tab_loop.py              # 自动循环标签页
│   ├── tab_nkt.py               # NKT 激光控制标签页
│   ├── tab_osa.py               # OSA 光谱标签页
│   └── tab_test_data.py         # 测试数据回放标签页
│
└── tools/
    └── setup_nkt_x64_dll.py     # NKT DLL 环境配置工具
```

**外部依赖目录**（位于 `autocapture` 的父级）：

```
../Native_64_lib/       # 原生 64 位 DLL
../NKT/                 # NKT Photonics SDK + NKTPDLL
../NKTPDLL/             # NKTPDLL x64 DLL
../thorlabs_tsi_sdk/    # Thorlabs TSI SDK
../roi_processor/       # ROI 处理器
```

---

## 使用指南

### 首次使用 — 硬件测试

1. 打开程序后进入 **Hardware Test** 标签页
2. 点击 **Scan all NKT ports** 扫描激光器 COM 口
3. 依次完成 Extreme ON → RF ON → Apply emission 测试
4. 使用 **Capture Test Frame** 测试相机连接
5. 使用 **Ping OSA** 测试光谱仪网络连接

### 自动采集循环

1. 在 **Camera** 标签页设置 ROI、曝光、增益
2. 在 **NKT** 标签页配置激光波长和功率
3. 切换至 **Loop** 标签页，配置扫描参数
4. 点击 **Start Loop** 开始自动采集

### 数据格式

- **图像数据**: TIFF（单帧）/ HDF5（多帧序列）
- **光谱数据**: CSV
- **日志**: 文本日志文件

---

## 注意事项

> ⚠ Windows 可能在拔插 USB 后重新分配 COM 口，重新扫描即可恢复连接。
>
> ⚠ NKT DLL（NKTP_DLL）必须在专用线程中初始化，避免 Qt IBHandler 跨线程错误。
>
> ⚠ 打包后首次运行可能需要从 `_internal/` 目录复制必要 DLL 到可执行文件同目录。

---

## 许可

本项目仅供内部研究使用。

---

## 联系方式

- 作者: Denghui Pan
- GitHub: [denghuipan/KiraluxAutoCapture](https://github.com/denghuipan/KiraluxAutoCapture)

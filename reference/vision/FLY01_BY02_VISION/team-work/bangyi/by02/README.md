# FLY-01 BY-02 视觉观测模块

这是可接洽项目的第一版 PC 视觉模块：沿用 BY-01-R1 红色目标检测，当前电脑的 NumPy、Pillow 即可运行图片与 GIF。输出带框画面、观测 JSONL 和供 Work 审核的反馈提案。K230 的结果报文入口已预留；相机标定、真实USB数据模式和正式闭环仍待实物到位后接续。

## 直接开始

在本目录打开终端：

```powershell
& 'D:\Anaconda3\python.exe' .\run_vision.py
```

程序会运行随包 8 张自制图片，并在新建的 `runs/时间戳/` 中输出结果。打开其中 `preview.html` 查看带框画面。也可以从任意位置调用本目录内 `run_vision.py` 的完整路径；默认样例按脚本位置查找。

本次实际检查环境：Python 3.13.9 / NumPy 2.3.5 / Pillow 12.0.0。没有安装额外软件，没有连接 K230、相机、串口、FPGA 或电机。

## 先看这些文件

| 文件 | 用途 |
|---|---|
| `run_vision.py` | 主入口；默认只读样例图片 |
| `fly01_vision/settings.py` | 集中配置；搜索 `装车后调整` / `实物到位后调整` |
| `VISION_USAGE.md` | 图片、GIF、K230结果回放及可选视频/相机的用法 |
| `VISION_OUTPUT_PROPOSAL.md` | 输出字段、坐标、时间和项目接洽约束 |
| `HARDWARE_PRESET.md` | 当前硬件预设、K230 USB/GPIO线索与待确认项 |
| `ASSEMBLY_TUNING.md` | 装车后逐项修改什么设置、需要测什么 |
| `config/assembly_override.example.json` | 可复制的装配配置草案，默认未标定 |
| `examples/image_run/preview.html` | 本机真实执行生成的离线样例结果 |
| `HANDOFF.md` | 本轮完成内容、验证和未完成范围 |

## 当前识别范围

首轮识别红色卡片／色块：一个合格连通块为 VALID，无目标为 NO_TARGET，多个为 AMBIGUOUS 并且不选目标。它不是通用物体识别模型。样例为此前项目自制图片，不是摄像头录像；GIF与K230 JSONL样例也都是合成回放。

默认不填方位角、米制距离或机体位置。`project_proposals.jsonl` 中的 BLOCKED 表示缺项已明确，不是识别程序崩溃。正式模型步号由 Work 绑定，视觉帧号不能直接充当神经步号。

K230 到位后继续复用本模块的观测结构和项目适配器；其固件采集与识别调用、真实数据传输、曝光时钟映射需要按实物实现。程序不产生 DN 或电机命令，停止逻辑由正式系统独立负责。

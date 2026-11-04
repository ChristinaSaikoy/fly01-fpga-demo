# 运行与接洽说明

## 1. 依赖

必要依赖为 NumPy 2.3.5、Pillow 12.0.0，当前电脑已安装。`requirements.txt` 记录本次环境，不要求修改 Work 的科学运行环境。

OpenCV 是普通视频文件／PC摄像头入口的可选依赖。本次没有安装、没有实际验证这两条硬件／编解码通道；缺少 OpenCV 时程序会返回明确错误、记录 FAILED 和 INPUT_ENDED，不保留旧目标作为有效输出。

## 2. 运行方式

以下命令在本任务目录执行。`--output` 必须是不存在的新目录；已有结果受到保护。

### 图片目录：当前可直接运行

```powershell
& 'D:\Anaconda3\python.exe' .\run_vision.py --source images --input .\samples\images --output .\runs\images_01
```

也可把 `--input` 换成一张 PNG/JPG/BMP/WebP。目录按文件名排序；它不代表原始拍摄时间顺序。

### GIF逐帧回放：当前可直接运行

```powershell
& 'D:\Anaconda3\python.exe' .\run_vision.py --source gif --input .\samples\sequence.gif --output .\runs\gif_01
```

GIF会按文件顺序尽快处理，不按媒体时钟睡眠。`media_time_ms` 只是媒体时间，主机执行耗时另记。随包GIF封装了原来的8个自制场景，不是真实相机采集。

### K230消息文件：当前可检查协议接洽

```powershell
& 'D:\Anaconda3\python.exe' .\run_vision.py --source k230-jsonl --input .\samples\k230_messages.jsonl --output .\runs\k230_01
```

这是结果报文回放，不运行K230。随包消息由PC对原图片做像素检测后生成，带有合成来源标记。无相机原图时，带框输出是明确标注 `DETECTION DIAGRAM ONLY` 的示意画面。

### 未来可选：视频／电脑摄像头

确认环境有 OpenCV 后可用：

```powershell
& 'D:\Anaconda3\python.exe' .\run_vision.py --source video --input .\my_video.mp4 --max-frames 200 --output .\runs\video_01
& 'D:\Anaconda3\python.exe' .\run_vision.py --source camera --max-frames 100 --output .\runs\camera_01
```

摄像头设置见 `camera.index/requested_width/requested_height/requested_fps`。只有显式选择 camera 才会打开相机。实际分辨率按帧记录，不保证请求的帧率或相机曝光时间已获取。K230只有确认固件提供普通摄像头服务后才能尝试该模式。

### 覆盖装车设置

```powershell
& 'D:\Anaconda3\python.exe' .\run_vision.py --config .\config\assembly_override.example.json --output .\runs\configured_01
```

复制示例后修改，不把未经测量的标定标志改成 true。JSON `null` 对应 Python `None`。

## 3. 输出

- `annotated/frame_*.png`：带框图；预览镜像不会修改数值坐标。
- `observations.jsonl`：每行一个视觉观测；最后一行 INPUT_ENDED 清空目标。
- `project_proposals.jsonl`：逐观测接入草案；列出缺失的标定、时钟与神经步号。
- `settings_used.json`：实际使用的完整设置。
- `summary.json`：处理数量、分类统计、环境、错误和明确的验证范围。
- `preview.html`：离线预览，不依赖网络。

退出码：0＝此次视觉处理完成；1＝运行失败，详情见 summary；2＝参数/配置/已有输出目录等入口错误。summary的PASS只表示输入被处理，不代表识别准确率、神经系统、K230或实物闭环通过。

## 4. 程序接入API

```python
from fly01_vision.settings import load_settings
from fly01_vision.pipeline import VisionPipeline
from fly01_vision.project_adapter import build_project_proposal

settings = load_settings()
pipeline = VisionPipeline(settings, session_id, process_monotonic_clock_domain)
observation, corrected_rgb = pipeline.process_rgb(
    rgb_uint8_array,
    frame_id=visual_frame_id,
    source=source_metadata,
    received_ns=host_monotonic_receive_time_ns,
)
proposal = build_project_proposal(observation, target_neural_timestep_id=work_assigned_step)
```

这段是调用形式；session、时间戳和步号由调用者提供。RGB必须是uint8 H×W×3；OpenCV默认BGR应先转RGB。K230已解析报文交 `pipeline.process_k230(record, ...)`；本轮没有串口接收服务。每次进程/会话重建pipeline，不沿用旧frame_id。

调用者须周期调用 `pipeline.poll(now_ns, same_clock_domain)`；它能返回陈旧状态，但不是后台线程。输入结束调用 `pipeline.ended()`。即使进程崩溃、阻塞或poll未执行，独立电机看门狗也必须自行停止；本模块没有电机连接。

## 5. 自身软件检查

```powershell
& 'D:\Anaconda3\python.exe' -m unittest discover -s .\tests -v
```

仅检查软件边界和样例真值；没有安装新依赖，没有触发项目真板套件。

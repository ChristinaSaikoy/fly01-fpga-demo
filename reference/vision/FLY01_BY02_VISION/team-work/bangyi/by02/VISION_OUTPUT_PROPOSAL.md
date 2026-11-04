# 视觉输出与 FLY-01 接洽提案

任务范围：视觉观测模块。基线为 GitHub `ChristinaSaikoy/fly01-neurofpga` 的 `edebc9768346023ba02fa9cdf285472724ebf87d`。当前入口不访问 FPGA 或电机；下面定义供 Work 接手的接口。

## 1. 输出层级

1. `BY02_VISION_OBSERVATION_V1`：从图像像素或导入K230检测得到的观测。
2. `BY02_PROJECT_FEEDBACK_PROPOSAL_V1`：复用项目反馈字段的接入草案；不能把缺字段的候选直接交给冻结编码器。
3. 正式 `FeedbackFrame v0.1 → 冻结编码器 → 神经计算 → DNFrame → 冻结运动映射`：由 Work 完成接洽和合同检查。此模块不实现后两段。

## 2. 观测字段

| 字段 | 含义 |
|---|---|
| `schema` | `BY02_VISION_OBSERVATION_V1` |
| `session_id/frame_id` | 本视觉进程会话和递增帧号；不是FPGA物理generation或神经步号 |
| `status` | VALID/NO_TARGET/AMBIGUOUS/STALE/ERROR/REJECTED/INPUT_ENDED；VALID仅表示检测到唯一图像目标 |
| `width/height` | 经旋转和传感器镜像纠正后的图像尺寸 |
| `components` | 连通块面积、质心和边框；多目标保留诊断，但不选择 |
| `bounding_boxes_xyxy_exclusive` | `[x0,y0,x1,y1)`，右/下边界不含在内 |
| `selected_center_xy` | 唯一有效目标的像素质心；无效时null |
| `normalized_offset_xy` | `[2*u/(width-1)-1, 2*v/(height-1)-1]`；图像右正、下正；不是弧度 |
| `image_relation` | IMAGE_LEFT / IMAGE_RIGHT / IMAGE_CENTER，使用可配置的像素中心死区 |
| `preview_center_xy` | 仅预览坐标；预览镜像不改数值观测 |
| `geometry` | 标定状态、方位角、单位射线及米制几何是否确认；未知字段null |
| `eligible_for_live_control` | 本模块默认false；正式系统应独立检查时钟、时效与几何 |
| `stop_required/stop_mechanism` | 本轮不允许据此使能运动；要求外部看门狗，不是已发出停机命令 |

源信息位于 `source`：

- `kind`：IMAGE_FILE / GIF_REPLAY / VIDEO_REPLAY / CAMERA / K230_JSONL。
- `capture_time_ns/capture_clock_domain/capture_time_verified`：真正采集时间及其时钟；文件未知时null，不能用读取时间替代。K230记录远端ticks时标为未同步。
- `media_time_ms`：GIF或视频的媒体时间；不是原始曝光时间。
- K230另记录 `remote_session_id/remote_frame_id`，不覆盖PC帧身份。
- `received_monotonic_ns/processed_monotonic_ns/clock_domain` 位于观测顶层；只在同一进程的单调时钟域比较。跨进程、跨设备不可直接相减。

## 3. 必须保留的坐标和时序语义

冻结编码器的方位角左正、右负，单位rad，机体系x向前/y向左/z向上。只有实际内参、去畸变输入、水平安装与外参都确认后，才根据测得参数计算方向。方向射线为无量纲；没有深度时 `relative_position_body_m` 仍为null。

`FeedbackFrame[k]` 只能作用于神经步 `k+1`。视觉帧可能来自不同频率或录像，不能把视觉frame_id当k。函数 `build_project_proposal(obs, target_neural_timestep_id=t)` 只在Work显式提供`t>=1`时生成候选k=t-1，仍要求主机绑定模型时钟、会话和时效；CLI默认不提供t。

适配器仅在单目标、明确在线来源、采集时钟确认、方向/安装标定、米制机体位置和方位角一致、明确模型步号全部成立后，返回 `READY_FOR_INTEGRATION_REVIEW`。其中 `feedback_frame` 也只是冻结编码器读取字段的子集，不是完整BODY合同自动验收。其余返回 `BLOCKED`、`blocking_reasons` 与 `feedback_frame=null`。

首轮只做转向，Work可评审单独的工程方向输入适配；这不意味着必须采购深度相机。本包先明确已有Body反馈合同的缺项，不把单位射线或固定假距离冒充实测位置，也不宣称新的方向输入合同已经获准。

## 4. 无目标、多目标和陈旧输入

- 无目标：NO_TARGET，选中质心和方向null，不保持上一目标。
- 多目标：AMBIGUOUS，不暗中选最大/最近目标。
- 重复／倒序：拒绝、清除有效选择。
- RGB或K230报文校验/处理异常：API先作废旧观测再抛错；CLI记录失败和结束状态。
- 超时：`poll()`检查同域时间；250ms是接收后时效草案。调用方需要周期调用；进程崩溃或阻塞必须由独立执行器看门狗处理。
- EOF／指定帧数结束：写INPUT_ENDED，清除选择。

中性视觉或神经输入不保证电机停止。运动限幅、失联超时、物理急停、恢复使能由执行器层单独负责；前进速度若由外部设定，材料中应标明来源。

## 5. K230报文预设

每行一个UTF-8 JSON，schema固定为 `FLY01_K230_DETECTION_V1`：

```json
{"schema":"FLY01_K230_DETECTION_V1","session_id":"board-boot-id","frame_id":0,"width":640,"height":480,"capture_time_us":null,"objects":[{"bbox_xyxy_exclusive":[110,200,190,280],"center_xy":[149.5,239.5],"area_px":6400}]}
```

以上数字是协议示例。`fly01_vision/k230_protocol.py`提供校验、组包与坐标纠正；`VisionPipeline.process_k230()`是PC程序接入点。板端采集与检测实现要按实际固件补齐，USB/UART接收器也未在本轮实现。该JSONL不是O8 F108报文，不能直接发送给FPGA。

板端OpenMV风格 `(x,y,w,h)` 如需接洽，应明确转换为 `[x,y,x+w,y+h)`；LAB红色阈值也不能直接照搬PC的RGB阈值。K230重新启动应换session，帧号从0开始；ticks回绕和跨设备时钟映射由接收器处理，不直接当作主机时间。

## 6. Work 接手清单

1. 读取观测并核实来源、坐标和时间域。
2. 决定相机方向观测如何进入正式反馈合同；保留冻结编码器身份。
3. 将合格观测分配到模型k/k+1，不无限缓存旧帧。
4. 按主机实际需要接O8 UART；不让K230消息绕过协议检查。
5. 独立集成运动限幅与停止机制，再进行实物和性能验收。

依据：[冻结编码器](https://github.com/ChristinaSaikoy/fly01-neurofpga/blob/edebc9768346023ba02fa9cdf285472724ebf87d/src/common/interfaces/visual_encoder/ENGINEERING_VIRTUAL_VISUAL_ENCODER_V1_0.py)、[冻结编码合同](https://github.com/ChristinaSaikoy/fly01-neurofpga/blob/edebc9768346023ba02fa9cdf285472724ebf87d/src/common/interfaces/visual_encoder/DEMO-1_SENSORY_ENCODER_V1_0.json)。

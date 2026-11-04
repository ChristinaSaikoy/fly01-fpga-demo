# O7 PACKED10 协议与无损边界

版本 `F1070001`；能力 ID `F1071C01`。不兼容/不重新解释 F1060001。固定单一编码，没有隐藏的自适应模式。当前仅离线验证，真实上板待准确批准。

## 请求布局

0x1000 起，32-bit word 地址升序；Vivado DATA 属性的高地址优先转换仍集中在既有 transport codec。

| word | 内容 |
|---:|---|
| 0 | magic F107C001 |
| 1 | version F1070001 |
| 2 | 实际物理 reset generation |
| 3 | frame |
| 4 | 解码后事件数 N，0..942 |
| 5 | 固定编码标记 0x00010000，bit0 DN enable，仅 0x10000/0x10001 合法 |
| 6 | request ID，必须等于 frame |
| 7 | CRC32/IEEE：little-endian words0..6 与压缩 payload；初始/最终 xor FFFFFFFF，poly EDB88320 |
| 8.. | ceil(10N/32) 个 payload 字 |
| 最后 | seal F107C0DE |

每个事件原样为 10-bit：bit9 噪声类别、bits8:0 local index。连续事件按最低位起连续放入 bitstream，低地址字先，不加权重或时刻。最高末字未使用位全部为零，非法 padding 拒绝。零事件仍有完整 9 字头尾，不是隐式省略帧。

`packet_words = 9 + ceil(10N/32)`；N942 最大 304 字，分两段有依赖屏障的 burst。固定头部 CRC 绑定的是实际编码 payload，不把主机 SHA 当硬件 SHA。

## 无损依据与非法输入

冻结编码器只接受311个 Q∈{0,2458} 和471个本地噪声 index。每类 local 严格升序、唯一，只有类别/index 属性。刺激 index0..470，噪声512..982；471..511/983..1023 不合法。刺激先、噪声后；同一个 local 的刺激和噪声是两个不同事件，不去重。

主机先拒绝非法/重复/顺序输入才 pack。FPGA CRC 处理时解码到原有有界事件 RAM，校验顺序/范围/数量/padding，完整包、CRC、代际/frame/消费条件通过后才送原核心。坏包不得向核心接受任何事件/提交。没有 FPGA RNG，没有预计算未来反馈。

理论科学 host 允许最多311+471=782事件；协议容量942是更宽的合成协议边界；目前动态轨迹最大180，三者分开。Codec tests 用独立 bit oracle、所有 N0..942、1895正向/2878拒绝向量，并无损转码 O6真实9223包。真实同 CRC、不同合法20事件碰撞 2FB28A8C 不得伪装重放。

## 消费、重放、故障与 reset

采用 O6 的逐事件精确语义重放 RAM：解码后与实际上一帧接受的事件逐个比对。相同输入/代际/frame/flags 幂等，不再提交；不同事件即使 CRC 相同也拒绝。当前只支持 PACKED10，旧/其他编码即使表示相同输入也明确拒绝，不声称跨两种受支持编码兼容。

结果59字实际被消费完后，下一个完整合法请求才能受控 ACK；读取旧57字不足以 ACK。valid 最后发布，错误下 invalid，不能用旧结果继续输出。半包1s超时、接收/解码背压、DRAIN/RUN reset、4+512原 reset guard 保留。buffer RAM 不要求物理清零，packet validity 被清除后旧 RAM不能被使用。

## 输出：原字段不删，额外增加两个实测计数

前528字与 O6 同样布局/语义，仅明确版本、stamp、packet_words、word_count 更新为 O7。前471 state、32 DN、饱和/overflow/drop/core cycles、身份、错误及提交/重放/拒绝/超时等全部保留。

| 位置 | 内容 |
|---|---|
| 0x000 / 054 / 060 | F1071C01 / F1070001 /530 |
| 0x100..0x93C | 原528字结果，原57字尾部字段均保留 |
| 0x940，新增word528 | decode_cycles：有待解码事件时的处理周期，含同步重放读等待，不含无关 host idle；N..2N，零事件0 |
| 0x944，新增word529 | protocol_cycles：首 word 接收至 ARM 提交的 FPGA 时钟周期，含包间 host等待、CRC校验和事件 drain，不含 core RUN |

full=530字，minimal=从0x85C起59字。两计数在 ARM 锁存，重放/半包不会改写前结果的已锁存计数。50MHz 下 cycles/50000=ms；core cycles仍是原核心自己的计数，不把这些值当端到端整帧延迟。

## 验证范围

Icarus/XSim 各6 seed×300=1800全状态，逐个监测核心真正接收的解码事件，要求与冻结序列精确同序；完整视图与minimal等价。46项协议故障包括全部旧门槛、padding、编码标记、跨word边界、无核心刺激的半包和真实CRC碰撞。

官方 JTAG AXI IP 复用完全相同的2R/2W组件参数和端口，没有重新配置，也没有声称其内部行为已仿真。完整新 bit 的硬件集成、5400与50Hz只能在准确批准后实测。

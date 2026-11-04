# HY-04｜生产 O8 最小兼容仿真补包

与既有 `HY04_O8_PRODUCTION_BUILD_2026-10-19` 并排放置，或用 `--production` 指定其解压路径。**不是 WORK-11 观察版，不需要板卡，不修改生产 RTL，不生成或烧录 bit。**

复用 WORK06 Vivado 2025.2 验证目录中的原始 `tb_o8_full.sv`、`tb_o8_ownership.sv`、协议 include 和 seed0 向量。full 测试包括 BASELINE/V_L/V_R 各100步，逐步核对471字状态、32路DN累计、饱和/溢出、协议身份和完整/最小视图；ownership 测试8项。不是完整6种子/三轮5400步、不是线上相机、不是资源/时序验收。

输入固定为生成好的冻结向量，不让你重新猜科学模型。文件逐字节复制原验证输入；向量旧 manifest 哈希按 LF 生成，而现有 Windows 文本为 CRLF，因此入口同时验证本补包实际字节摘要和旧 manifest 的 LF 规范化摘要，不重写向量。

```powershell
python -B run_sim.py
python -B run_sim.py --sim --backend xsim --vivado-bin 'D:\AMDDesignTools\2025.2\Vivado\bin'
# 如同时已安装 Icarus，可做交叉复核，不自动安装或替换工具：
python -B run_sim.py --sim --backend both --vivado-bin 'D:\AMDDesignTools\2025.2\Vivado\bin'
```

首条只验证输入、不启动仿真。每次仿真写新 outputs 目录，保留完整命令、编译/仿真日志及 RESULT；要求明确 PASS 标志、逐步/用例数量和无 Fatal/Error，不能仅看退出码。任一门槛失败即停，保留原日志，不改RTL或放松检查。

这些是无IP依赖的显式非工程RTL仿真入口，不调用历史故障 `launch_simulation` 包装器，也不需要启动 Vivado GUI/MCP。它不替代你本人独立构建及资源、时序、DRC/告警报告。补包仅本地保存，未外发；本机实测结果在 outputs，若未运行或失败必须如实注明。

## Work 本机验证（2026-10-19）

Christina / Vivado 2025.2 XSim：8项 ownership + seed0 的300步完整状态、DN与协议检查通过，原始日志在 `D:\FPGA-AUTO\tasks\WORK-13\camera_fpga_mvp\evidence\hy_sim_03_relative_tcl`。使用明确PASS标志和300条步骤记录，不是退出码推断。未做新的完整5400步、综合/布局布线或上板。

开发失败保留：`hy_sim_01` Icarus ownership通过、300步仿真达到240s上限，该早期入口未保存超时进程的部分标准输出，因此不能确定其最后完成步骤；不是功能通过。`hy_sim_02_xsim` 因绝对反斜杠/中文 Tcl 路径被启动包装层转义而未运行TB。最终入口把 Tcl 复制到本次工作目录并传相对路径，且直接写进程日志并有界回收自有超时进程；RTL/向量保持原样。这里不声称两个仿真器全通过或证明哪个更快。

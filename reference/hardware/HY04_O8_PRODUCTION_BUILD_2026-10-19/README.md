# HY-04 私有团队生产 O8 构建输入包

来源是已验收 UART 生产 O8（历史 bit SHA 93399a70…），不是 WORK11 观察版。
源码/约束/35 份 ROM 初始化输入及已升级的 jtag_axi_o5 XCI 逐字节对应同一
2025.2 native build02。SOURCE.json 记录来源；FILES_SHA256.json 是唯一文件清单。
生成 ROM 的原数据库不需要传给你：冻结 .mem 本身是本次综合的最小输入。
本包不声称可以重新生成科学模型，也不包含硬件授权、账号、安装器或原始数据库。

先解压到本机目录，安装 Python 和 Vivado 2025.2（Artix-7 器件），执行：

```powershell
python -B build.py
python -B build.py --build --vivado 'D:\AMDDesignTools\2025.2\Vivado\bin\vivado.bat'
```

第二条的工具位置按你本机修改。输入路径已经可迁移；源内 ROM 相对路径不改，
每次在新 outputs/RUN_ID 中构建。不需要 GitHub 仓库、participant 的 D 盘目录、
完整历史封包或远程开发板。不默认安装 MCP。不会编程/烧录或联系外部系统。

工具/参数：2025.2、xc7a35tfgg484-2、50 MHz、2 Mbps UART、maxThreads=4。
IP Tcl 已包含 read_ip、参数读回校验和 generate_target；锁定就停，不自动改参。
保留完整普通 Warning。源码、XDC、IP 参数均未改，只改构建路径/升级停止保护/
新制品名。WORK12 仅完成输入闭包与入口自检，没有运行此完整构建。

请交一次当前 RUN_ID 的 RESULT、完整 process.log、资源/时序/DRC/CDC/总线偏斜
报告及准确 bit hash。新制品不应假定与历史 bit 字节一致。进程退出 0 或存在 bit
都不等于整体通过；原始 ERROR/Critical 必须阻塞，异常记录不得删改。
历史资源仅供比较：LUT8370 / FF8014 / BRAM40/50 / DSP1，WNS+.149/WHS+.060ns。
资源/报告仍由 HY-04/总控审核，不自动把输出或本机无错误写成系统/上板通过。

本包只本地存放，尚未推送/发送。正式仓库 HEAD 来源为 edebc976…，README
中的选取源码不构成此构建闭包。HY-04 如修改线程/隔离输出，单列差异和理由，
有限对照且保留失败，不修改冻结模型或连续重跑挑绿灯。

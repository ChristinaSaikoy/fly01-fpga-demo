---
name: exact-state-check
description: Compare complete integer state and output traces from a frozen reference and another implementation, finding the first divergent step without operating hardware.
---

# 逐步整数轨迹比较

适用于固定模型和输入下的软件/RTL/板端完整整数快照比较；不用于浮点近似误差评估、只读摘要比较或生物有效性判断。输入来源需独立，不能用同一个生成器同时写出期望和实际后称为独立验证。

每个输入为UTF-8 JSONL。首行为身份对象：`{"model":"frozen-v1","inputs_sha256":"<64位小写hex>","state_words":471,"dn_slots":32}`。后续每行包含`step`、完整整数数组`state`和`dn`；步号从0连续递增。整数不能用浮点或布尔代替。不同实现应导出相同数值语义，符号/补码转换须在适配层明确；本脚本不隐式转型。

从本技能目录执行 `python -B scripts/compare_trace.py expected.jsonl actual.jsonl`。成功输出`EXACT_MATCH`和比较步数，失败返回非零并定位首个差异。先核对首行冻结模型/输入身份，再逐步比较全部状态和DN；拒绝空轨迹、维度变化、跳步、缺失和重复JSON键。脚本只读输入，不生成或修改黄金数据。

来源：FLY-01的O5全状态验收和HY-06「软件黄金通过但HDL WATCHDOG」审核。经验是把输入/参考/实际执行身份及完整覆盖分开，不能只检查最终动作或摘要。项目病例见`../../report/ai_collaboration.md`；内部证据E02/E08。

已验证效果：本轮在新临时目录以小型合成正例及状态差异、DN差异、缺步、空输入、非法维度、布尔值、身份不一致等反例运行，结果见`../../checks/skill_reuse_result.json`。这只验证比较工具，不表示新RTL或真板通过。若缺完整独立轨迹、输入身份不明或定点语义改变，停止作exact结论并交由主分析者处理。

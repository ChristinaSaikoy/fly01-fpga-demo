# 项目技能包 v0.1

最终代码包导出到skill/，本目录是制作源。以下脚本仅依赖Python标准库，不接设备，不安装全局技能。项目整体许可未决定，使用/再分发范围需在最终发布时确定。

| 技能 | 用法 | 已验证效果/失效条件 |
|---|---|---|
| exact-state-check | 完整JSONL整数轨迹逐步比较，见SKILL.md | 合成正例与差异/缺步/身份反例；不接受浮点近似、未知输入身份或仅最终动作 |
| readonly-handoff-audit | 独立清单校验交付树，见SKILL.md | 合成篡改/缺失/多余/路径反例与实际独立副本完整性；不证明清单真实性或硬件通过 |
| transport_evidence_template.md | 手工填写分层性能与版本对照模板 | 从O7/O8实际案例总结；模板本身未做跨项目用户验证，不宣称通用收益 |

项目证据来源：report/ai_collaboration.md和内部evidence_index.json。首次最小复用结果在checks/skill_reuse_result.json；这是工具验证而非新增神经exact、RTL或整机验收。每个技能都保留适用范围、实际脚本、失败拒绝条件和来源。

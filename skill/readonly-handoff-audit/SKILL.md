---
name: readonly-handoff-audit
description: Verify a delivered file tree against a separately retained SHA256 manifest without regenerating the package, rejecting altered, missing, extra or escaping inputs.
---

# 只读交付树校验

适用于拿到已解压源码/数据交付后核对文件完整性，不负责解压、运行交付代码、科学重算、数字签名或判定HDL/硬件通过。

输入为交付根目录与独立保留的JSON清单，结构：`{"files":[{"path":"rtl/core.sv","sha256":"<64位小写hex>","bytes":123}]}`。路径使用相对POSIX形式；清单可以在根目录外。若在根内，仅排除清单文件自身。原始清单及其来源须可信且另行保留；攻击者能同时替换文件和清单时，哈希不能证明真实性。

运行 `python -B scripts/verify_manifest.py ROOT MANIFEST`。默认核对完整普通文件集合及每项大小/摘要，拒绝缺失、多余、重复条目、绝对路径、父目录越界、符号链接或Windows重解析点；不自动补录或重写清单。脚本不运行交付中的生成器，不把未列入文件默默纳入可信集合。

来源：HY-06交付中的run_checks.py会重生成资产与清单，总控选择保留原包、独立复算，查出软件PASS与HDL失败并存。对应工程摘要见`../../report/ai_collaboration.md`，证据E08。摘要校验通过只证明与给定清单一致，后续实际编译/仿真仍要读原始日志与制品身份。

本轮最小复用使用新临时目录的合成文件树，检查正常通过和篡改、漏项、额外文件、逃逸、重复路径、空清单等拒绝行为；另对已复制到独立目录的实际项目快照清单校验。记录见`../../checks/skill_reuse_result.json`和`source_reproduction.json`。无法读取的文件或不支持的清单格式应停止并解释，不通过重封包消除错误。

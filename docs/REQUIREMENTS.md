# REQUIREMENTS（由 docs/SPEC.md v1.0 映射，规格为准）

范围：Windows 10/11、本机同卷普通目录、普通文件、单用户单任务，Python 3.11+，核心与界面分离（tkinter + CLI）。
不支持：跨卷、网络共享、符号链接/junction、目录重命名、正则/模糊匹配、内容识别、去重、压缩、监控、定时。
只改文件位置与名称，不改字节；程序不删除用户文件（仅清理本次创建且仍为空的目录）。

| ID | 需求 | 关键约束 | 验收 |
|----|------|----------|------|
| R01 (F01) | 扫描 | 默认第一层；`recursive` 可选；扩展名筛选大小写不敏感；跳过隐藏/系统/链接/硬链接/状态目录/`Organized` 并给原因；读取失败明确列出 | A01 A02 A12 |
| R02 (F02) | 重命名 | 固定顺序：字面量大小写敏感替换主名 → 前缀/后缀 → 可选 `_NNN`；空查找串非法；保留扩展名；编号从 1、默认 3 位、全批次、按 (casefold(rel), rel) 排序；空规则 = no_op | A02 A03 A08 |
| R03 (F03) | 分类 | none / extension / month(UTC)；目标固定 `<root>/Organized/`；无扩展名 → `no_extension`；分类展平；仅重命名保留父目录；`Organized` 为链接则拒绝 | A04 A05 A06 |
| R04 (F04) | 预览 | 逐项原路径/新路径/动作(rename/move/move_and_rename/no_op)/状态(ready/conflict/skipped)/原因；汇总计数；CSV(UTF-8)/JSON 导出；计划含 schema_version、plan_id、root、rules、size/mtime_ns/SHA-256、摘要；计划存应用状态目录；预览不改源、不建目标；计划是数据；导入校验 | A07 A08 A12 |
| R05 (F05) | 冲突 | 目标存在、批内同目标、仅大小写改名、非法 Windows 名、越界、父路径是文件、目标是另一待移动源(含交换/循环)、路径过长 → 整个计划阻止；casefold 比较；不自动加后缀 | A09 A10 A11 A12 |
| R06 (F06) | 执行 | UI 先预览后 Apply 并确认；改规则/目录使预览失效；CLI plan/apply 两步，`apply` 需 `--yes`；执行前全批复检、零移动失败；逐项移动前复检；无覆盖移动；变化即停；部分失败保留成果且可撤销；SHA-256 一致 | A13–A18 A25 |
| R07 (F07) | 日志与恢复 | 状态目录；run_id、计划快照、逐操作 intent→done 追加日志(fsync)；日志写失败不得继续移动；状态集 planned/running/completed/partial_failed/interrupted/undone/undo_partial_failed/needs_review；同根目录排他锁(进程退出自动释放)；启动核对中断批次，歧义 → needs_review，不猜测，不自动继续 | A18 A19 A24 |
| R08 (F08) | 撤销 | 仅同根最近一个未撤销批次；逆序；全批预检(身份+SHA-256、原位置空闲、在根内)，失败整次不启动；中途失败即停可重试；撤销也写 intent→done；重复撤销 no_op；只清理本批创建的空目录 | A20–A23 |
| R09 | CLI | `plan ROOT --rules --out`、`apply plan --yes`、`history --root`、`undo RUN_ID --yes`；退出码 0/2/3/1；stderr 无裸 traceback | A25 |
| R10 | UI | 四区：Folder & Rules / Preview / Results / History & Undo；冲突时 Apply 禁用；执行中禁用重复提交与规则编辑；英文短句错误 | A14 A25 A27 |
| R11 | 交付质量 | 干净安装、版本记录、完整测试、验收矩阵；未验证项如实标注 | A26 |
| R12 | 演示数据 | 36 文件 fixture（PDF10/JPG8/TXT8/CSV6/无扩展名4，3 子目录）与冲突 fixture，独立预期映射固定在测试数据中 | A25 主演示（阶段 6 素材本轮不做） |

本轮范围（TASK.md）：阶段 1–5；阶段 6（截图、录屏、Upwork 草稿）不做；不发布、不推远程。

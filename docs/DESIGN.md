# DESIGN

## 模块（`src/fileorganizer/`）
- `names.py`：Windows 名称/路径校验（保留名、非法字符、尾点/空格、越界、长度）、链接/reparse 检测、SHA-256。
- `rules.py`：`Rules`（严格解析，未知键报错）。
- `scanner.py`：只读扫描，返回 `Entry`（相对路径、大小、mtime_ns、file_id、sha256、状态、原因）。
- `planner.py`：`Plan/PlanItem`、映射生成、统一冲突检测 `detect_conflicts`、摘要 digest、导出 CSV/JSON、`load_plan`、`validate_for_apply`。
- `state.py`：状态目录、根目录排他锁（`msvcrt.locking`，句柄随进程退出释放）、`Journal`（追加 JSONL + fsync）。
- `runs.py`：`apply_plan`、`undo_run`、`recover`、`history`；无覆盖移动 `safe_move`（`os.rename`，Windows 上目标存在则失败，从不使用 `os.replace`）。
- `cli.py` / `__main__.py`：CLI。`ui.py`：tkinter，只调用核心。

## 关键决策
1. **计划是数据**：JSON，所有路径为根内相对路径（`/` 分隔），导入时重新校验；digest = SHA-256(canonical JSON(root, rules, items 映射与来源指纹))，只防意外变更。
2. **文件身份** = (size, mtime_ns, file_id=`st_dev:st_ino`, SHA-256)。同大小改内容靠 SHA-256，替换文件靠 file_id。
3. **冲突检测只有一份实现**：`detect_conflicts(root, entries)`，规划和导入/执行前复检共用。casefold 比较。
4. **执行事务模型**（非数据库事务，不宣称断电安全）：预检全批 → 建 run 目录并写 `planned`（同时验证日志可写）→ `running` → 每项：复检源/目标 → 写 `intent`(fsync) → `os.rename` → 校验 SHA-256 → 写 `done`。任何失败即停。
5. **日志**：`runs/<run_id>/run.json`（元数据+计划快照，不变）+ `journal.jsonl`（事件追加）。状态完全由日志最后的 `state` 事件推导。目录创建也写 `mkdir` 事件，撤销时仅在为空时 `rmdir` 这些目录。
6. **恢复**：发现 `running/undo_running` 末态的批次 → 写 `interrupted` → 对每个只有 intent 的操作比对源/目标位置、file_id、SHA-256：仅「目标匹配且源缺失」判已移动、「源匹配且目标缺失」判未移动，其余 → `needs_review`（不动文件，给出路径）。恢复不继续移动。
7. **撤销**：只对根内最近一个未撤销且有成功操作的批次；全批预检；逆序 `intent → rename → done`；失败即停并记录；重试只处理剩余项；已 undone 批次重复撤销为 no_op。
8. **锁**：`<state>/locks/<sha1(normcase(realpath(root)))>.lock`，非阻塞独占字节锁；apply/undo/recover 持锁。
9. **故障注入**：`runs.Hooks`（`pre_move`、`move`）与可替换 `Journal` 工厂，测试用；生产默认空。
10. **UI**：线程执行规划/执行，主线程轮询；规则变量任何变动即清空预览并禁用 Apply。
11. **退出码**：`PreflightError`→2；运行中失败/需复核→3；其他异常→1（简短英文消息，`--debug` 才打印 traceback）。

## 状态机
`planned → running → completed | partial_failed | interrupted → (reconcile) completed | partial_failed | needs_review`；
撤销：`undo_running → undone | undo_partial_failed | (interrupted → reconcile) | needs_review`。

## 已知取舍
- 路径长度 ≥260 一律预检失败（不启用长路径）。
- 硬链接文件被跳过并说明（不纳入）。
- 日志 fsync 保证的是操作系统层面的持久写，不承诺掉电事务安全。

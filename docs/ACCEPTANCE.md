# 验收矩阵 A01–A27

所有结果都来自一次干净安装运行：提交 `3529669`，2026-11-03，Windows 11 build 26200，Python 3.11.9，pytest 8.3.4。
运行命令：`python -m pytest -v -rA -p no:cacheprovider tests --junitxml=junit.xml`
总计：**139 通过 / 0 失败 / 0 跳过**。证据：`docs/evidence/pytest-full.log`、`docs/evidence/junit.xml`；
主演示另见 `docs/evidence/demo-check.log`、`docs/evidence/demo_manifest.json`。环境与步骤见 `docs/TEST_REPORT.md`。

所有文件操作测试都在 pytest 的 `tmp_path` 临时沙盒中进行。下面的「状态」只有三种：
- **通过**：在真实 Windows 上实际运行并通过；
- **部分通过**：已运行的部分通过，但有某个子场景是模拟的或没有运行（已具体写明）；
- **未验证**：没有运行。

| ID | 状态 | 测试（文件::名称） | 实际结果与说明 |
|----|------|------------------|----------------|
| A01 | 通过 | test_planning::test_A01_default_first_level_only, test_A01_recursive_switch, test_A01_extension_filter_case_insensitive, test_A01_unreadable_file_listed_not_ignored | 默认只返回 `a.txt`；开启递归后返回 3 层文件；`Pdf`/`.PDF` 都能匹配 `a.PDF`、`b.pdf`；读取失败的文件显示为 conflict 并给出 "read error"，计划被阻止（读错误是用 monkeypatch 注入的 PermissionError） |
| A02 | 通过 | test_A02_special_names, test_A02_extension_case_preserved | 中文+空格+多点 `报告 最终.v1.2.pdf` → `P_报告 最终.v1.2_S.pdf`；`my file.tar.gz` 按最后一个点拆分；`Makefile` 仍无扩展名；零字节文件的 SHA-256 = e3b0…b855；`.JpG` 的大小写被保留 |
| A03 | 通过 | test_A03_fixed_order_replace_prefix_suffix_number, test_A03_replace_is_literal_case_sensitive, test_A03_empty_find_illegal, test_A03_numbering_order_casefold_then_original, test_A03_1000_files_unique_not_truncated | `report_old` → `old_report_new-s_001`（前缀里的 `old` 没有被替换）；`(c)` 按字面量替换；`abc` 不匹配 `ABC`；空查找串报错；排序为 a < b < C（casefold 优先）；编号跨目录连续；1000 个文件全部唯一，`_1000` 没有被截断 |
| A04 | 通过 | test_A04_classify_by_extension | `a.PDF` → `Organized/pdf/a.PDF`；无扩展名 → `Organized/no_extension/` |
| A05 | 通过 | test_A05_month_is_utc ×5 | 用固定 UTC mtime 验证：2025-12-31T23:30→2025-12、2026-01-01T00:00→2026-01、01-31T23:59:59→2026-01、02-01T00:00→2026-02、闰日→2024-02。本机时区为 UTC+8，所以按本地时间计算会得到不同结果 |
| A06 | 通过 | test_A06_no_classify_keeps_parent_and_flatten_conflicts | 不分类时保留 `x/`；分类后两个 `invoice.pdf` 都标为 conflict（"same target"） |
| A07 | 通过 | test_A07_preview_does_not_touch_source, test_A07_plan_cannot_be_written_inside_root | 预览并保存计划前后，SHA-256 快照和目录集合都相同；没有创建 `Organized`；计划/CSV 写入源目录时被拒绝 |
| A08 | 通过 | test_A08_deterministic_mapping, test_A08_empty_rules_and_empty_folder_are_explainable_noops, test_A08_export_csv_json | 两次生成的映射和 digest 相同，plan_id 不同；空目录 total=0；无规则时 no_op，原因为 "no rules configured"；CSV 带 BOM 且中文可读；JSON 含规格要求的字段；已存在的输出文件不会被覆盖 |
| A09 | 通过 | test_A09_existing_target_and_batch_duplicates_block, test_A09_batch_duplicate_targets_block_all_involved, test_cli::test_A25_cli_blocked_plan_exit_2_and_cannot_apply | 已存在目标或批内同名都会阻止计划；被阻止的计划经 CLI apply 返回 2，源树 SHA-256 不变，也没有创建 `Organized` |
| A10 | 通过 | test_A10_invalid_windows_names_block ×5, test_A10_trailing_dot_or_space_block ×2, test_A10_case_only_rename_blocked, test_A10_case_insensitive_collisions_block, test_A10_same_target_differing_only_by_case, test_A10_empty_new_name_blocks | CON/aux、`: ? <`、末尾点或空格、仅大小写改名、`B.txt` 与已有的 `b.txt` 冲突、`a.txt`/`A.txt` 映射到同一目标、空主名，全部阻止 |
| A11 | 通过 | test_A11_swap_and_cycle_rejected, test_A11_parent_path_is_file_rejected, test_A11_long_path_precheck_fails_clearly | 交换和三元循环在 validate_for_apply 中被拒绝；名为 `Organized` 的文件挡在父路径上时报 "is a file"；≥260 字符的路径预检失败，提示 "not supported" |
| A12 | **部分通过** | test_A12_boundary_escape_in_tampered_plan ×8, test_A12_tampered_plan_digest_detected, test_A12_malformed_plan_files, test_A12_plan_roundtrip_through_file, test_A12_junction_and_hardlink_never_included, test_A12_root_that_is_a_junction_is_refused, test_A12_target_through_junction_rejected, test_A12_organized_link_refused, test_A12_target_on_different_volume_rejected_SIMULATED, test_cli::test_A25_cli_tampered_plan_exit_2 | `../`、`..\`、`C:/`、`/`、`a/../..`、`//`、`CON`、`./` 都被拒绝；篡改过的 digest 和格式错误的计划被拒绝；**真实 junction**（`mklink /J`）和**真实硬链接**都被跳过或拒绝，junction 外的文件没有被纳入。**不同卷：只做了模拟**（伪造 `st_dev`），因为本机没有第二个本地 NTFS 卷（G: 是 FAT32 的 Google Drive 同步盘，Z: 可用空间为 0）。**文件符号链接**（`mklink` 不带 `/J`）没有单独测试；代码对所有 reparse point 一律拒绝 |
| A13 | 通过 | test_runs::test_A13_same_size_content_change_detected_even_with_same_mtime, test_A13_source_deleted, test_A13_source_replaced_by_identical_copy, test_A13_target_created_after_preview, test_A13_second_apply_of_same_plan_moves_nothing | 同大小、同 mtime 但内容改变时，靠 SHA-256 发现；同内容、同 mtime 的替换文件靠 file_id 发现；删除源或创建目标后零移动、没有产生 run；同一计划第二次 apply 不会再移动 |
| A14 | 通过 | test_ui::test_A14_* ×17 | 真实 Tk 窗口：没有预览时 Apply 不可用；7 个规则输入和目录中任何一个改动都会作废预览并禁用 Apply；改动之后才返回的扫描结果被丢弃；双击 Apply 只确认一次、只移动一次、只产生 1 个 run；执行中所有输入和按钮都被禁用，关闭窗口被拒绝；冲突时 Apply 不可用；两个窗口用同一计划时，第二个被拒绝（"Nothing was moved"）；另一实例持锁时显示错误、零移动。变异检查：去掉 UI 中的作废和冲突判断后，有 10 个 A14 用例失败。确认框和提示框换成了记录器，原生对话框本身没有被点击 |
| A15 | 通过 | test_runs::test_A15_A20_demo_apply_verify_undo_full_restore, test_A15_noop_and_skipped_untouched, test_A15_mixed_plan_only_moves_ready_items | 36 个演示文件逐一对照**独立冻结**的映射和 SHA-256，全部一致；日志中 36 个 intent 和 36 个 done；纯 no_op 计划返回成功、不产生 run、文件不变；被跳过的 `b.pdf` 字节没有变化 |
| A16 | 通过 | test_A16_target_inserted_at_last_moment_is_never_overwritten, test_A16_os_rename_semantics_refuse_overwrite | 在写入 intent 之后、移动之前创建目标文件：INTRUDER 的内容保持不变，源文件仍在原处，结果为 done/failed/not_run 且后续停止；另外直接验证了 `safe_move` 在 Windows 上目标存在时抛出 FileExistsError |
| A17 | 通过 | test_A17_injected_failure_at_item_n, test_A17_real_locked_file_stops_the_run | 第 3 项注入 PermissionError：结果为 done,done,failed,not_run,not_run，计数为 2/1/2，日志中 3 个 intent、2 个 done、1 个 failed，之后不再尝试；**真实占用**（打开的文件句柄）同样在该项停止。说明：权限失败是注入的，没有用真实 ACL 拒绝来测 |
| A18 | 通过 | test_A18_unwritable_log_dir_means_zero_moves, test_A18_first_journal_write_fails_zero_moves, test_A18_midrun_journal_failure_stops_and_recovery_reconciles, test_A18_journal_fails_before_intent_stops_before_that_move | 日志目录无法创建（该位置是一个文件，真实 OS 错误）或第一次写入失败时零移动；中途写 done 失败时立即停止，后续文件未动，恢复核对后正确记为 done，并能撤销。日志故障是用 Journal 子类注入的，真实的磁盘写满没有测试 |
| A19 | 通过 | test_A19_kill_after_intent_before_move, test_A19_kill_after_move_before_done, test_A19_kill_after_done, test_A19_kill_after_last_done_reconciles_to_completed, test_A19_ambiguity_both_locations_needs_review, test_A19_ambiguity_neither_location_needs_review, test_A19_ambiguity_content_mismatch_needs_review, test_A19_needs_review_stays_when_user_recreates_file_with_different_identity, test_A19_needs_review_resolves_when_original_is_put_back_exactly, test_A19_torn_journal_line_is_tolerated | 子进程在三个时间点用 `os._exit(9)` **真实终止**；"移动后 done 前"被正确判为已移动（没有因为缺 done 就认定未移动）；两边都有、两边都无、内容不符都转为 needs_review，文件保持原样，之后的 apply 和 undo 都被拒绝；残缺的日志尾行被容忍。只覆盖这三个确定的终止点，没有覆盖任意时刻终止或断电（规格不要求） |
| A20 | 通过 | test_A15_A20_demo_apply_verify_undo_full_restore, test_A20_undo_preserves_preexisting_dirs, test_A20_created_dir_with_foreign_file_is_kept | 撤销后 36 个文件的路径和 SHA-256 与原始快照完全相同，目录集合也相同；执行前已有的空目录 `Organized/pdf` 被保留；本批新建、但里面有用户新文件的目录被保留 |
| A21 | 通过 | test_A21_target_modified, test_A21_target_replaced_same_content, test_A21_target_missing, test_A21_original_location_occupied | 四种情况都返回 "Undo refused"，并列出具体文件；树和目录都不变；状态仍为 completed；用户放在原位置的新文件没有被覆盖 |
| A22 | 通过 | test_A22_partial_run_undoes_only_successes_and_repeat_is_noop, test_A22_only_latest_batch_can_be_undone | 部分失败的批次只撤销 2 个成功项，然后完全还原；再次撤销提示 "already"，没有副作用；撤销旧批次被拒绝（"most recent"），按顺序撤销后完全还原 |
| A23 | 通过 | test_A23_undo_fails_at_item_n_then_retry_does_not_repeat, test_A23_undo_process_killed_then_reconciled_and_retried, test_A23_undo_killed_after_intent | 撤销按逆序进行，在第 3 项失败后停止；重试只处理剩余的 f1、f0；撤销进程在恢复文件后、写 undo_done 前被真实终止，核对后判为已恢复，重试后完全还原 |
| A24 | 通过 | test_A24_lock_excludes_second_holder_in_process, test_A24_two_processes_only_one_executes, test_A24_lock_released_when_process_killed, test_A24_lock_is_per_root, test_A24_threads_double_submit_moves_once | 两个**真实进程**竞争：持锁进程停在执行中途时，第二个进程的 apply 和 undo 都返回 2，最终只有 1 个 run；持锁进程被杀后锁自动释放（`msvcrt.locking`，不是靠锁文件是否存在）；4 个线程同时提交只完成 1 次。网络盘或云盘上的锁行为没有测试（规格不支持） |
| A25 | 通过 | test_cli::test_A25_* ×14, test_ui::test_A25_cli_and_ui_same_mapping_and_result | 对两个相同的演示目录，CLI 和 UI 生成的映射和规则相同，执行后的树相同，run 状态和 done 集合也相同；退出码：0（plan/apply/undo/无变更），2（缺 --yes、未知命令、目录/计划/run 不存在、坏规则、输出在源目录内、被篡改的计划、锁占用、被阻止的计划、needs_review 时的新任务），3（真实占用导致的部分失败、needs_review），1（模拟 bug，stderr 中没有 Traceback）。所有子进程调用都断言 stderr 不含 "Traceback" |
| A26 | 通过 | 见 `docs/TEST_REPORT.md` | 新目录 `git clone` → 新 venv → `pip install .` → `pip install -r requirements-dev.txt` → 139/0/0；入口 `fileorganizer.exe` 可以运行；`tools/run_demo_check.py` 用已安装的包跑主演示，17/17 通过（预览 36 ready/0 conflict → 执行 36 → 日志 36+36 → 撤销 36 → 树和 SHA-256 全部还原 → 冲突 fixture 被阻止且没有改动）。已记录 Windows/Python/依赖版本和提交 SHA。说明：构建后端 setuptools 的具体版本没有记录 |
| A27 | **通过（机器核对 + 截图逐张核对）** | `tools/a27_ui_run.py` | 真实 tkinter 窗口，SendInput 真实点击与键盘，原生文件夹选择框与确认框；演示副本 + 冲突夹具，FILEORGANIZER_STATE_DIR 指向临时目录。选目录、按扩展名分类、预览、应用、撤销。15/15 项磁盘与日志核对通过（应用后 36 目标存在且 SHA-256 一致、日志 36 intent + 36 done；撤销后树与 SHA-256 与原始一致、日志 36 undo_intent + 36 undo_done；冲突夹具未改动）。 | `docs/evidence/a27/`（8 张截图、a27_checks.json、两份日志、A27_SUMMARY.md）。截图核对（2026-11-04 补做）：8 张截图已逐张打开，与两份日志、`demo_expected.json` 和机器核对对照，无矛盾：04 中可见的 14 行预览与前 14 条 intent 按顺序一致，08 中可见的 13 行撤销结果与前 13 条 undo_intent 一致，06/07/08 的 run id 与 a27_checks.json 一致（明细见 A27_SUMMARY.md）。**显示问题（未改代码）**：表格中多数行的 `_` 没有画出来（屏幕上是 `Doc data.v1 001.csv`，日志和磁盘上是 `Doc_data.v1_001.csv`），看起来是行高裁掉了下划线；磁盘上的名字正确。 |

## 交付门槛对照（规格第八节）

- A01–A27：A27 已用真实窗口完成，机器核对 15/15，截图已逐张核对（见上）。A12 的“不同卷”仍只有模拟测试。
- 核心安全用例无跳过：满足（0 跳过）。
- 干净安装成功：满足（A26）。
- 主演示 36 个文件的内容与路径完全还原：满足（CLI 演示检查 + 自动化 UI 流程）；人工界面演示尚未进行。

结论：A01–A27 均有证据；A12 跨卷仅模拟。（第 6 阶段更新，2026-11-04；截图核对补做于同日）

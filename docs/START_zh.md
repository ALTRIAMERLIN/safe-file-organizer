# Safe File Organizer 中文启动说明

个人作品集演示项目，演示数据全部为合成内容。

## 环境
- Windows 10/11（已在 Windows 11 build 26200 实测）
- Python 3.11 及以上（python.org 安装包，自带 tkinter；实测 3.11.9）
- 运行时无第三方依赖；测试依赖 `pytest==8.3.4`（见 `requirements-dev.txt`）

## 安装
```powershell
cd safe-file-organizer
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install .
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## 启动界面
```powershell
.\.venv\Scripts\python -m fileorganizer ui
```
1. 「Folder & Rules」点 Browse 选目录，设置替换/前缀/后缀/编号/分类。
2. 点 Preview 查看每个文件的新路径和状态。有冲突时 Apply 不可用。
3. 点 Apply，确认文件数和目录后执行。
4. 「Results」看逐项结果；「History & Undo」看历史，可撤销最近一次。
改任何规则或目录，旧预览立即作废，需要重新 Preview。

## 命令行
```powershell
python -m fileorganizer plan 目录 --rules rules.json --out 计划.json   # 只生成计划，不动文件
python -m fileorganizer apply 计划.json --yes                         # 执行
python -m fileorganizer history --root 目录
python -m fileorganizer undo RUN_ID --yes
python -m fileorganizer recover --root 目录                           # 只核对中断批次，不移动文件
```
退出码：0 成功/无变更；2 参数或预检失败（未移动任何文件）；3 执行/撤销中途失败或需人工复核；1 未预期异常。

## 演示与测试
```powershell
python tools\make_demo_workspace.py demo_workspace
python tools\run_demo_check.py 输出目录      # CLI 跑完整演示并生成 manifest.json
python -m pytest -q tests
```
应用状态（计划、日志、锁）默认在 `%APPDATA%\SafeFileOrganizer`，可用 `--state-dir` 或环境变量 `FILEORGANIZER_STATE_DIR` 覆盖。

## 限制
不支持跨卷、网络共享、链接/junction、目录重命名、正则匹配等；不承诺断电下的事务安全；撤销只恢复路径与内容，不恢复目录时间、ACL 等元数据。详见 README 与 docs/ACCEPTANCE.md。

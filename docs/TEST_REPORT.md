# 测试报告（阶段 5：干净安装与全套验收）

| 项目 | 值 |
|------|----|
| 日期 | 2026-11-03（本地 UTC+8），pytest 开始 22:18:41，用时 12.45 s |
| 被测提交 | `3529669910a0d82fa049143e03c031419d3a9c0f` |
| 系统 | Windows 11，`platform.platform()` = `Windows-10-10.0.26200-SP0`（build 26200），NTFS 系统盘 |
| Python | 3.11.9（python.org 安装版，tkinter / Tk 8.6） |
| 运行时依赖 | 无 |
| 测试依赖（`pip freeze`，干净 venv） | pytest==8.3.4, pluggy==1.7.0, iniconfig==2.3.1, packaging==26.3, colorama==0.4.6 |
| 构建后端 | setuptools（`pyproject.toml` 要求 `>=68`，由 pip 构建隔离从 PyPI 下载；具体版本未记录，未锁定） |
| pip | 24.0 |

## 干净安装步骤（实际执行）

在系统临时目录下新建一个全新目录（不复用工作区，也不复用旧 venv）：

```powershell
git clone <工作区仓库> <新目录>          # HEAD = 3529669
cd <新目录>
py -3.11 -m venv .venv
.\.venv\Scripts\python -m pip install .
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -v -rA -p no:cacheprovider tests --junitxml=junit.xml   # -> pytest-full.log
.\.venv\Scripts\fileorganizer.exe --version                                               # -> fileorganizer 1.0.0
.\.venv\Scripts\python tools\run_demo_check.py demo_out                                   # -> demo-check.log, manifest.json
```

确认 CLI 使用的是已安装的包：`fileorganizer.__file__` = `<新目录>\.venv\Lib\site-packages\fileorganizer\__init__.py`。
pytest 测的是克隆出的源码（`pyproject.toml` 里 `pythonpath = ["src"]`）；演示检查脚本通过 `python -m fileorganizer` 调用已安装的包。

## 结果

| 项目 | 结果 |
|------|------|
| pytest | **139 通过，0 失败，0 跳过，0 错误**（exit 0） |
| 入口脚本 | `fileorganizer.exe --version` exit 0 |
| 主演示检查（`tools/run_demo_check.py`） | **17/17 项检查通过**（exit 0） |

各文件数量（来自 junit.xml，参数化用例分别计数）：test_planning 56、test_runs 42、test_ui 22、test_cli 15、test_fixtures 4，合计 139。

## 证据文件（`docs/evidence/`）

| 文件 | 内容 |
|------|------|
| `pytest-full.log` | 完整 `pytest -v -rA` 输出 |
| `junit.xml` | 机器可读结果（每个用例的名称与耗时） |
| `demo-check.log` | 主演示的 17 项检查 |
| `demo_manifest.json` | 演示规则、执行前/执行后/撤销后的树与 SHA-256、计划汇总、完整 run 日志（167 个事件）、每条 CLI 命令的输出与退出码 |

公开前已对证据做脱敏：本机路径替换为 `[MASKED]` / `<OUT>`，主机名替换为 `[HOST]`，用户名已移除。脱敏只改了路径和名称字符串，没有改动任何数字或结果。

## 测试后的变更

在提交 3529669 上测试之后，只新增或修改了文档（`docs/ACCEPTANCE.md`、`docs/TEST_REPORT.md`、`docs/evidence/*`、`PROGRESS.md`、`docs/TASKS.md`），没有改代码或测试。最终提交前在工作区又跑了一次全套测试，结果见 PROGRESS.md。

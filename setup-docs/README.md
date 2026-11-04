# 环境搭建与验证指引（Windows / CMD）

本目录记录 **Windows 10 + cmd.exe** 下把 `feishu-task-engine` 跑起来所需的全部前置条件、安装步骤与验证命令。
所有命令均在真机 `cmd.exe` 中逐条执行验证，不是纸面推导。

| 文档 | 解决什么问题 |
|---|---|
| [`01-验证步骤-CMD版.md`](./01-验证步骤-CMD版.md) | **主清单**。Step 0~6 逐步验证：解释器锚定 → 静态自检 → 依赖安装 → 飞书链路 → 配置 → 引擎冷启动 → 发布链路。含失败对照表（报错原文 → 原因 → 修法） |
| [`02-chrome-win64-手工安装指引.md`](./02-chrome-win64-手工安装指引.md) | `playwright install chromium` 报 **403 AccessDenied**（地区限制）时，如何手工下载 `chrome-win64.zip` 并放进 Playwright 的目录结构使其生效 |
| [`03-lark-cli-安装配置指引.md`](./03-lark-cli-安装配置指引.md) | `lark-cli` 未安装 / 未授权 / 机器人不在群里（`230002`）的完整处理路径，含安装位置选择、双身份授权、凭证存放位置 |

## 三分钟速览：这个项目的前置依赖分五层

1. **系统**：Windows 交互式桌面会话（`run_workflow.py` 依赖 `win32gui` 操作微信窗口，无 GUI 无法运行）。
2. **Python**：3.12+ 与 `requirements.txt` 中的 10 个包（`pywin32` / `pyautogui` / `opencv-python` / `Pillow` / `psutil` / `pyperclip` / `playwright` / `PySocks` 等）。
3. **通信**：飞书官方 CLI `lark-cli`，且 **bot 与 user 两个身份都 ready**、具备 `im` 权限、机器人**已在目标群里**。
4. **配置**：`feishu_config.json`（真实 `chat_id`）与 `yt_config.json`（下载器路径 / 代理 / cookies），两者都不入库。
5. **媒体与发布**：`yt-dlp` + `ffmpeg` + Node.js（下载链路）；微信登录态 + `WeChatAppEx` 窗口 + 11 张模板 PNG（发布链路）。

## 两个最容易踩的坑

- **解释器不一致**：`task_configs.json` 里的阶段命令写的是字面 `"python"`，由 `PATH` 解析。依赖装在 3.12，阶段却跑到 3.13 上就会 `ModuleNotFoundError`。**每次开窗口先把 3.12 目录前置到 `PATH`。**
- **CMD 变量提前展开**：`set "PY=..." && "%PY%"` 必然失败（解析整行时就替换了 `%PY%`）。所有命令按"一行一个"粘贴，不要用 `&&` 串联。

## 说明

- 文档中的 `oc_…` / `cli_…` / `ou_…` 等实例标识已做脱敏，替换成自己的实际值即可。
- `install_deps.bat` 与 `setup.bat` 内写死了作者本机路径，**不要直接双击**，等价命令见 `01` 文档 Step 2。

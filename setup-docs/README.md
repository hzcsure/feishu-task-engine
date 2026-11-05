# 环境搭建与验证指引（Windows / CMD）

本目录记录 **Windows 10 + cmd.exe** 下把 `feishu-task-engine` 跑起来所需的全部前置条件、安装步骤与验证命令。
所有命令均在真机 `cmd.exe` 中逐条执行验证，不是纸面推导。

## 先跑一次一键体检

不想逐条手工敲，在**仓库根目录**执行：

```bat
check-env.bat
```

只读、不装任何东西、不改系统环境变量。它把本目录所有检查项跑一遍，输出 `OK / WARN / FAIL`，
退出码 `0`=全部通过、`1`=有 FAIL、`2`=只有 WARN。

窗口行为随启动方式自动切换，不需要额外操作：

| 启动方式 | 结束后 |
|---|---|
| 双击 `check-env.bat` | **停在 `Press any key to close this window`**，报告不会一闪而过 |
| 已打开的 cmd 窗口里敲脚本名 | 不暂停（窗口本来就留着） |
| `-Json` / `-NoPause` | 不暂停（自动化、计划任务、CI 用这两个） |

判定依据是 `%CMDCMDLINE%` 里是否出现脚本名 —— 双击时 cmd 以 `/c "<脚本全路径>"` 启动，脚本名必然在里面；
在已有控制台里手动执行则只有解释器路径。

| 参数 | 作用 |
|---|---|
| `-Json` | 输出 JSON（纯 ASCII 转义，任何代码页都能解析）；隐含不暂停 |
| `-DryRun` | 只列将要检查的项目，不执行外部命令 |
| `-Online` | 额外探测 pypi / aliyun / github / Chromium 镜像连通性 |
| `-PythonPath "C:\...\python.exe"` | 强制指定解释器（默认自动挑 3.12） |
| `-NoPause` | 强制不暂停（计划任务、CI、从 PowerShell 调用时建议显式加上） |
| `-Pause` | 强制暂停，即使在已有控制台里运行 |

用法示例：

```bat
check-env.bat
check-env.bat -Json > env-report.json
check-env.bat -Online
check-env.bat -NoPause
```

脚本本身：`check-env.bat`（入口，绕过 PowerShell 执行策略）+ `scripts/check_env.ps1`（逻辑）。
体检通过后再按下表按需深挖。

| 文档 | 解决什么问题 |
|---|---|
| [`01-验证步骤-CMD版.md`](./01-验证步骤-CMD版.md) | **主清单**。Step 0~6 逐步验证：解释器锚定 → 静态自检 → 依赖安装 → 飞书链路 → 配置 → 引擎冷启动 → 发布链路。含失败对照表（报错原文 → 原因 → 修法） |
| [`02-chrome-win64-手工安装指引.md`](./02-chrome-win64-手工安装指引.md) | `playwright install chromium` 报 **403 AccessDenied**（地区限制）时，如何手工下载 `chrome-win64.zip` 并放进 Playwright 的目录结构使其生效 |
| [`03-lark-cli-安装配置指引.md`](./03-lark-cli-安装配置指引.md) | `lark-cli` 未安装 / 未授权 / 机器人不在群里（`230002`）的完整处理路径，含安装位置选择、双身份授权、凭证存放位置 |

## 体检覆盖的 10 组检查

| 组 | 内容 |
|---|---|
| 1 系统与会话 | Windows 版本、是否交互式桌面 |
| 2 解释器 | 候选清单、选定版本、PATH 首位是否一致 |
| 3 Python 依赖 | 10 个包逐个查「已安装版本 + 能否 import」 |
| 4 外部工具 | node / npm registry / yt-dlp / ffmpeg（走 `imageio_ffmpeg.get_ffmpeg_exe()`，不靠 PATH） |
| 5 lark-cli | 三个查找顺位、版本、bot 与 user 双身份 |
| 6 Chromium | 从 `browsers.json` 读期望版本，核对 `chrome.exe` + `INSTALLATION_COMPLETE` |
| 7 配置文件 | `feishu_config.json`（真实会话数 / 默认聊天）、`yt_config.json` |
| 8 cookies | `youtube_cookies.txt` 是否存在 |
| 9 发布链路 | 11 张模板图、`WeChatAppEx` 目录、微信进程、主窗口、视频号助手窗口（`WeChatAppEx` 进程） |
| 10 静态校验 | 全部 `.py` 语法 + 根目录 JSON 合法性 |

必须人工的三项（微信登录、模板截屏、真机发布）脚本只报缺失，不代做。

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
- `install_deps.bat` 已自动定位本机 CPython 3.12（原 `setup.bat` 已合并进来），可直接双击运行；等价命令见 `01` 文档 Step 2。

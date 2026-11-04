# feishu-task-engine 调试前验证清单（CMD 版）

> 本文替换 Git Bash 版步骤，全部命令可在 `cmd.exe`（Win+R → `cmd`）直接粘贴。
> 环境实测记录：Windows 10 · CPython 3.12.10 · lark-cli 1.0.98 · Chromium 156.0.8078.4 · commit `b72a095`
>
> 文中 `oc_xxx…`（群 ID）、`cli_xxx…`（App ID）、`ou_xxx…`（open_id）均为**脱敏占位符**，请替换成你自己的实际值。

---

## 粘贴前必读：两个 CMD 专属坑

| 坑 | 后果 | 对策 |
|---|---|---|
| 控制台默认 GBK（cp936） | 中文/emoji/JSON 输出乱码，甚至 `UnicodeEncodeError` | 每条命令前先 `chcp 65001`，并设 `PYTHONUTF8=1` |
| 阶段子进程用 PATH 上的 `python` | 依赖装在 3.12，子进程却跑 3.13 → `ModuleNotFoundError` | 每条命令前把 3.12 目录前置进 PATH |
| `set` 与 `%VAR%` 写在同一行 | `%PY%` 在 `set` 执行**之前**就被展开 → 报"不是内部或外部命令" | 一行 `set`，下一行再用 `%PY%`；**不要用 `&&` 串起来** |

**因此建议每次开新窗口都先粘这一段"会话前置"：**

```bat
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PY=C:\Users\hzc\AppData\Local\Programs\Python\Python312\python.exe"
set "REPO=C:\Users\hzc\WorkBuddy\2026-11-04-21-31-21\feishu-task-engine"
set "PATH=C:\Users\hzc\AppData\Local\Programs\Python\Python312;%PATH%"
cd /d "%REPO%"
```

> `PY` 和 `REPO` 是**本机实测路径**，换机器只改这两行（`set "REPO=<你的克隆目录>"`），文档其余命令全部使用相对路径或 `%PY%`。

> `set` 只在当前窗口有效（关闭即失效），不会污染系统环境变量 —— 这是安全的做法。
> 想永久生效就手动改"系统属性 → 环境变量 → 用户变量 Path"，**不要**用 `setx PATH "%PATH%"`（会截断超长 PATH 并覆盖系统变量）。
>
> **务必逐行粘贴（一次一行回车）**。CMD 在解析一整行时就把 `%PY%` 展开成字符串了，所以
> `set PY=... && "%PY%" --version` 这种写法必然失败（展开时 PY 还是空的）。本清单已全部按"一行一个命令"编排。

---

## Step 0　锚定解释器（30 秒）

```bat
"%PY%" --version
where python
python -c "import sys;print(sys.executable)"
```

**期望**

- `Python 3.12.10`
- `where python` 输出**两行以上**，第一行必须是 `...\Python312\python.exe`
- 第三行打印 `...\Python312\python.exe`

**若第三行是 `...\.workbuddy\binaries\...\python.exe`（3.13）** → 前面的 `set PATH` 没生效，回到"会话前置"重来。这是本项目最容易踩的一个坑。

---

## Step 1　静态自检（不联网、不写文件）

> **偷懒路线**：Step 0~6 的检查项已封装成只读脚本，一条命令即可全查一遍：
>
> ```bat
> check-env.bat
> ```
>
> 输出 10 组 `OK / WARN / FAIL`，退出码 `0`=全通过、`1`=有 FAIL、`2`=只有 WARN。
> 加 `-Json` 出机器可读结果，加 `-DryRun` 只列检查项，加 `-Online` 附带网络探测，
> 加 `-NoPause` 强制不暂停（计划任务 / CI）。双击运行时它会停在
> `Press any key to close this window`，报告不会一闪而过。
> 下面的手工命令仍然值得走一遍 —— 出问题时你能一眼定位是哪一层。

```bat
"%PY%" -c "import ast,glob,json;[ast.parse(open(f,encoding='utf-8').read()) for f in glob.glob('**/*.py',recursive=True)];[json.load(open(f,encoding='utf-8')) for f in glob.glob('*.json',recursive=False)];print('AST+JSON OK')"
```

**期望**：只打印 `AST+JSON OK`。若报 `SyntaxError` 或 `JSONDecodeError`，说明仓库文件被改坏了，`git status` 看一下。

```bat
"%PY%" -X utf8 task_engine.py --help
"%PY%" -X utf8 feishu_send.py --help
"%PY%" -X utf8 yt_download.py --help
```

**期望**：三行 `usage: ...` + 参数表。**`--help` 报错说明缺依赖，先做 Step 2。**

---

## Step 2　装依赖 + 解释器对齐

```bat
"%PY%" -m pip install -r requirements.txt yt-dlp imageio-ffmpeg
```

**期望结尾**：`Successfully installed ...`，且包含 `pywin32 opencv-python PyAutoGUI pyperclip Pillow psutil playwright PySocks yt-dlp imageio-ffmpeg`。

> **已知现象**：结尾可能报
> `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE. ... unknown package`
> 但包其实已落盘（用下面的 import 检查确认）。重跑一次或加 `--no-cache-dir` 即可。
> 国内加速可加：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

```bat
"%PY%" -c "import win32gui,pyautogui,cv2,PIL,psutil,pyperclip,yt_dlp,imageio_ffmpeg,socks;print('deps OK')"
```

**期望**：`deps OK`。**这一行才是依赖是否装好的唯一判据**，别信 pip 的退出码。

```bat
"%PY%" -X utf8 run_workflow.py --help
```

**期望**：`usage: run_workflow.py [-h] [--config CONFIG] [--stdin]`
（装 `pywin32` 之前这行必然是 `ImportError: No module named 'win32gui'`）

### Chromium（仅 `update_cookies.py` 用得到）

```bat
"%PY%" -m playwright install chromium
```

**大概率失败**：`server returned code 403 ... not available in your location`（CDN 地区限制）。
→ 走**手工安装**，完整步骤见 [02-chrome-win64-手工安装指引.md](02-chrome-win64-手工安装指引.md)。

---

## Step 3　飞书链路

> 前置：`lark-cli` 已安装并完成 bot + user 双身份授权。
> 从零安装见 [03-lark-cli-安装配置指引.md](03-lark-cli-安装配置指引.md)。

```bat
where lark-cli
lark-cli --version
lark-cli auth status --verify --json
```

**期望**

- `where` 命中 `...\cli-connector-packages\lark-cli.cmd`
- `lark-cli version 1.0.98`
- JSON 里 `"identities"` 下 **bot 和 user 都是 `"status": "ready"`**，且 `"verified": true`

```bat
lark-cli im +chat-list --json
```

**期望**：返回 `"ok": true` 和至少一个 `chat_id`（`oc_` 开头）。

```bat
"%PY%" -X utf8 feishu_send.py --list
```

**期望**：打印形如

```
飞书聊天列表 (N 个):
  [group] 任务引擎调试   oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx  (normal)
  ...
```

> **注意**：这个脚本首次运行若发现没有 `feishu_config.json`，会**自动生成一份带占位 `oc_xxxx...` 的配置**。占位条目必须删掉，否则后续按名字找会话会失败。

```bat
"%PY%" -X utf8 feishu_send.py "ping"
```

**期望**：`发送文本到 [<默认会话>] ...` → `[OK] 发送成功! 消息ID: om_...`，飞书客户端里能看到这条消息。

**常见失败对照**

| 报错 | 原因 | 处理 |
|---|---|---|
| `230002 Bot/User can NOT be out of the chat` | 机器人不在目标会话里 | 建群时邀机器人：`lark-cli im +chat-create --as user --name "任务引擎调试" --bots cli_xxx` |
| `missing_scope: im:message.send_as_user` | 用 `--as user` 发消息，但该 scope 需单独申请 | 默认身份保持 `bot`；或用 `lark-cli auth login --scope "im:message.send_as_user"` 重新授权 |
| `not_configured` | 没执行过 `lark-cli config init --new` | 见 03 文档 |
| `无法解析 chat_id` / 找不到名字 | 配置里还是占位 `oc_xxxx` | 编辑 `feishu_config.json` 换成真实 `oc_` |

**不建议用 `--sync` 自动同步**：它只追加不删除，会把占位条目和真实条目混在一起（`feishu_send.py:266-293`）。手写 `feishu_config.json` 更干净。

---

## Step 4　配置文件

### 4.1 `feishu_config.json`

从零创建：

```bat
copy feishu_config.example.json feishu_config.json
notepad feishu_config.json
```

改成至少这样（把 `oc_` 换成 Step 3 拿到的真实值）：

```json
{
    "默认聊天名称": "任务引擎调试",
    "默认身份": "bot",
    "聊天列表": [
        {
            "名称": "任务引擎调试",
            "chat_id": "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "备注": "调试群：自己 + CLI 机器人"
        }
    ]
}
```

> `默认身份` 必须是 `bot`。设成 `user` 会因缺 `im:message.send_as_user` 直接失败。

### 4.2 `yt_config.json`

```bat
copy yt_config.example.json yt_config.json
notepad yt_config.json
```

或用项目自带引导（会**自动探测** yt-dlp / node / ffmpeg 的绝对路径并写回）：

```bat
"%PY%" -X utf8 setup_check.py
```

**`工具路径` 三项要落实成绝对路径**，否则子进程可能找不到：

```json
"工具路径": {
    "yt-dlp": "yt-dlp",
    "node": "C:\\Users\\hzc\\.workbuddy\\binaries\\node\\versions\\26.13.0-1\\node.exe",
    "ffmpeg": "C:\\Users\\hzc\\AppData\\Local\\Programs\\Python\\Python312\\Lib\\site-packages\\imageio_ffmpeg\\binaries\\ffmpeg-win-x86_64-v9.0.2.exe"
}
```

### 4.3 一键全量自检

```bat
"%PY%" -X utf8 setup_check.py
```

**期望**：8 项全 `[V]`，末尾 `所有检查通过！`

```
[V] lark-cli 安装     [V] lark-cli 授权      [V] feishu_config.json
[V] 默认聊天已设置    [V] yt-dlp 安装        [V] Node.js 安装
[V] ffmpeg 安装       [V] yt_config.json
```

> **坑**：`setup_check.py:265` 用 PATH 上的 `python` 去探测 `imageio_ffmpeg`。
> 如果没做"会话前置"，即使 3.12 里装了也会误报 `[X] ffmpeg 未安装`。

### 4.4 验证 yt-dlp 链路

```bat
"%PY%" -X utf8 yt_download.py --info "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

**实测结论（2026-11-04）**：命令能跑通到 yt-dlp 层，但会失败，原因是

```
ERROR: [youtube] ...: Sign in to confirm you're not a bot. ... Use --cookies-from-browser or --cookies
```

即**网络能通，卡在风控，必须提供 cookies**：

```bat
"%PY%" -X utf8 update_cookies.py
```

首次会打开可见的 Chromium 窗口 → 登录 Google → 回终端回车 → 生成 `youtube_cookies.txt`。
（所以 `update_cookies.py` 是**前置依赖**，Chromium 必须先装好，见 02 文档。）

代理可选：`yt_config.json` 里 `代理.启用 = true`，默认 `socks5://127.0.0.1:10888`（需自备代理，本机默认无监听）。

---

## Step 5　引擎冷启动

```bat
"%PY%" -X utf8 task_engine.py > engine.log 2>&1
```

另开一个窗口看日志：

```bat
type engine.log
```

**期望顺序**

```
已加载 2 个任务类型:
  - 下载YouTube视频 (yt_download)
  - 下载YouTube并发布到微信视频号 (yt_download_and_publish)
聊天目标: 任务引擎调试 [oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]
身份: bot
 发送启动通知... 启动通知 已发送
```

然后每 3 秒轮询一次（无心跳打印，静默属正常）。

**验收**：在飞书"任务引擎调试"群发 `帮助`，引擎回复命令列表即链路完整。

**三条必须知道的**

1. **`--daemon` 是假的**。`task_engine.py:1113` 只声明参数不实现，后台模式无效，必须前台跑（用 `start /b` 或另一个窗口）。
2. **不要开两个实例**。两个进程抢同一条消息，会重复回复、重复建任务。
3. **首次轮询会丢弃历史消息**（`task_engine.py:1046-1051`）。所以刚启动时发旧消息它不理你，得等启动通知发出后再发。

停止：`Ctrl+C`。

---

## Step 6　发布链路（微信视频号，最重的一步）

**三个硬前提，缺一不可**

1. 桌面版微信已登录，且 `WeChatAppEx` 进程在运行、**窗口可见**（不能最小化到托盘）
2. 屏幕分辨率/缩放与截图时一致（否则模板匹配全废）
3. `WeChatAppEx\` 目录下有 **11 张模板 PNG**（仓库 `.gitignore:15` 排除了，**必须自己截**）

需要的 11 张（名字即文件名，从 `wf_publish.template.json` 提取）：

```
首页-1.png  发表视频.png  添加描述.png  短标题.png  预览上传.png
文件路径.png 文件名.png   删除.png      封面预览.png 保存草稿.png
视频号助手.png
```

建目录并自测匹配：

```bat
mkdir WeChatAppEx
"%PY%" -X utf8 template_matcher.py "C:\some\shot.png" "WeChatAppEx\首页-1.png" 0.8
```

**期望**：打印匹配坐标与相似度。相似度 < 0.8 会判定失败 —— 说明截图缩放/主题不同，重截。

单独跑一次发布工作流（不经过飞书）：

```bat
echo {"工作流":[]} | "%PY%" -X utf8 run_workflow.py --stdin
```

（真实内容用 `wf_publish.template.json` 的 `工作流` 数组，`点位图` 路径相对 `WeChatAppEx\`）

---

## 附：本机当前状态快照（2026-11-04 实测）

| 项 | 状态 |
|---|---|
| CPython 3.12.10 | ✅ `C:\Users\hzc\AppData\Local\Programs\Python\Python312\python.exe` |
| 10 个 pip 依赖 | ✅ 全部 import OK |
| lark-cli 1.0.98 | ✅ bot + user 双 ready（App `cli_xxxxxxxxxxxxxxxx`） |
| 飞书会话 | ✅ 9 个，默认群"任务引擎调试" `oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| bot 发消息 | ✅ `om_...` 已送达 |
| Chromium 156.0.8078.4 | ✅ 有头启动 OK（手工装，见 02 文档） |
| yt-dlp / ffmpeg / node | ✅ 均可调用 |
| YouTube 解析 | ⚠️ 需 `youtube_cookies.txt`（风控，非网络） |
| 11 张发布模板图 | ❌ 待自行截屏 |
| 微信 `WeChatAppEx` | ❌ 未验证 |

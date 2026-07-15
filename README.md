<div align="center">

<img src="assets/workbuddy-invite-poster.png" alt="WorkBuddy 邀请海报" width="360" />

# 🐝 飞书任务引擎 · feishu-task-engine

### 一套由飞书机器人驱动的 YouTube 视频自动下载与微信视频号发布系统

> **手机端一句话登记任务，桌面端按计划自动执行。** 把"找视频 → 输标题 → 模拟点击发布"这条 5 分钟的人工流程，压缩成飞书聊天里的一次表单提交。

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)](#)
[![yt-dlp](https://img.shields.io/badge/yt--dlp-Latest-FF0000?logo=youtube&logoColor=white)](https://github.com/yt-dlp/yt-dlp)
[![License](https://img.shields.io/badge/License-MIT-green)](#)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)](#)
[![Made with WorkBuddy](https://img.shields.io/badge/Made%20with-WorkBuddy-00C896)](#)

[🎁 扫码注册 WorkBuddy 即获 2000 积分](#-workbuddy-邀请) · [📖 项目说明](项目说明_业务视角.md) · [🐛 提 Issue](https://github.com/hzcsure/feishu-task-engine/issues)

</div>

---

## 🎁 WorkBuddy 邀请

> **这个项目就是用 WorkBuddy（你正在用的 AI 办公搭子）从零搭起来的。**
> 扫码注册即可领取 **2000 积分**，一起把活儿干得漂亮。

<div align="center">

| 注册入口 | 邀请链接 |
|---|---|
| 📱 **扫码注册**（见上方海报） | <https://www.workbuddy.cn/events/invite?inviteCode=8ueyyequf3g24> |

</div>

---

## ✨ 项目亮点

| | 能力 | 简述 |
|---|---|---|
| 📩 | **飞书对话式操作** | 在飞书聊天窗口发一条"登记任务"，机器人引导填表，全程无需登录服务器 |
| 🎬 | **YouTube 一键下载** | 基于 `yt-dlp` + `EJS` 签名算法，支持断点续传、自动转码、Cookies 复用 |
| 🚀 | **视频号自动发布** | 通过 `pyautogui` + OpenCV 模板匹配，模拟人工操作自动完成发布流程 |
| 🔁 | **多阶段任务编排** | 「下载 → 发布」两阶段管线，阶段间数据通过 `context` 流转，已成功阶段重试不重跑 |
| 🛡️ | **去重与容错** | `.publish_history.json` 防重复发布；10 次连续失败自动熔断 |
| 🧩 | **适配器架构** | input-prepare / post-process 适配器模式，新增业务只需挂一个适配器 |
| ⏰ | **定时与即时** | 表单可填"执行时间"做定时任务，留空则立即执行 |
| 🔌 | **依赖配置化** | 代理、cookies、工具路径全部走 `*.json` 配置文件，不写死 |

---

## 🏗️ 架构一览

```
┌────────────────────────────────────────────────────────────────┐
│                          飞书消息窗口                            │
│  (用户发"登记任务" → 选类型 → 填表单 → 收到结果推送)                │
└───────────────────────────┬────────────────────────────────────┘
                            │  lark-cli
                            ▼
┌────────────────────────────────────────────────────────────────┐
│                     task_engine.py 任务引擎                       │
│  · 调度循环                                                        │
│  · 多阶段管线：context 在 stage 间传递                            │
│  · 失败/重试/状态持久化                                             │
└──────────────┬───────────────────────────┬──────────────────────┘
               │                           │
       Stage 1 ▼                    Stage 2 ▼
┌──────────────────────┐    ┌────────────────────────────┐
│   yt_download.py     │    │   run_workflow.py           │
│   · yt-dlp + EJS     │    │   · pyautogui 模拟键鼠        │
│   · ffmpeg 转码       │───▶│   · OpenCV 模板匹配           │
│   · 断点续传           │    │   · 复制到 WeChatAppEx/      │
│   输出: *.mp4 + _info │    │   输出: 发布到视频号            │
└──────────────────────┘    └────────────────────────────┘
```

---

## 🚀 快速开始

### 1️⃣ 环境要求

- **Python 3.12+**（推荐使用本地 CPython，不要用 Store 版）
- **Windows 10/11**（发布阶段依赖 `pywin32` 窗口管理）
- **Node.js 20+**（仅 `yt-dlp` 解 YouTube n-challenge 需要）
- **飞书 lark-cli**（WorkBuddy 连接器管理 → 飞书，登录后即可）

### 2️⃣ 一键安装依赖

双击运行 `install_deps.bat`，自动完成：
- `pip install -r requirements.txt`（pywin32 / pyautogui / opencv / pillow / psutil / playwright）
- `pip install yt-dlp imageio-ffmpeg`
- `python -m playwright install chromium`（仅 `update_cookies.py` 需要）

### 3️⃣ 首次环境检查

```bash
python setup_check.py
```

> 会自动检测 lark-cli 授权、yt-dlp/Node/ffmpeg、聊天配置、代理配置等。

### 4️⃣ 准备配置

```bash
# 复制配置模板（按需修改）
cp feishu_config.example.json feishu_config.json
cp yt_config.example.json     yt_config.json
cp sn.example.json            sn.json
```

必填项：
- `feishu_config.json` → `chat_id`（运行 `python feishu_send.py --sync` 自动获取）
- `youtube_cookies.txt` → 运行 `python update_cookies.py` 生成
- `yt_config.json` → 代理地址 / Node 路径 / ffmpeg 路径

### 5️⃣ 启动引擎

```bash
# 前台运行
python task_engine.py

# 后台常驻
python task_engine.py --daemon
```

启动后向飞书聊天窗口发送 `帮助` 即可看到所有可用命令。

---

## 💬 飞书命令一览

| 命令 | 说明 |
|---|---|
| `登记任务` | 开始登记新任务，按提示选类型、填表单 |
| `任务列表` | 查看所有任务及状态 |
| `查询任务 T-20260627-001` | 查看指定任务的阶段详情 |
| `取消任务 T-ID` | 取消待执行或已失败的任务 |
| `删除任务 T-ID` | 彻底删除任务记录 |
| `删除全部任务` | 清空所有任务 |
| `重试任务 T-ID` | 重新执行失败阶段（已成功阶段自动跳过） |
| `帮助` | 查看命令列表 |

---

## 🧪 业务场景

### 场景 1：仅下载 YouTube 视频
> 1. 飞书发 `登记任务` → 选 `下载YouTube视频`
> 2. 填视频链接 + 可选标题/描述/标签
> 3. 下载完成，机器人推送结果

### 场景 2：下载 + 自动发布到微信视频号
> 1. 飞书发 `登记任务` → 选 `下载YouTube并发布到微信视频号`
> 2. 填视频链接 + 标题(6-16字) + 描述 + 标签
> 3. 引擎自动两阶段执行：下载 → 复制到 `WeChatAppEx/` → 模拟发布
> 4. 完成后机器人推送最终结果

---

## 🧰 技术栈

**核心**
- `Python 3.12` · `pywin32` · `pyautogui` · `opencv-python` · `Pillow`
- `yt-dlp`（含 `EJS`/`nodejs` 解 n-challenge）· `ffmpeg`（imageio-ffmpeg）
- `playwright`（仅 `update_cookies.py` 用）

**通信与桥接**
- `lark-cli`（位于 `C:\Users\lm\.workbuddy\binaries\node\cli-connector-packages\`，飞书官方）
- 代理：`socks5://...`（yt-dlp）/ `http://...`（ffmpeg，支持混合协议端口）

**架构**
- 适配器模式（`adapters/publish_prepare.py` + `adapters/yt_download_to_publish.py`）
- 多阶段管线 + `context` 跨阶段共享 + `tasks.json` 持久化

---

## 📁 项目结构

```
feishu-task-engine/
├── task_engine.py             # 任务引擎主程序
├── feishu_send.py             # 飞书通信模块
├── yt_download.py             # YouTube 视频下载器
├── run_workflow.py            # 视频号发布工作流
├── template_matcher.py        # OpenCV 模板匹配
├── update_cookies.py          # YouTube cookies 更新
├── setup_check.py             # 环境检查工具
├── snapshot_qr.py             # YouTube 直播帧 QR 解析（独立工具）
│
├── adapters/                  # 适配器
│   ├── publish_prepare.py
│   └── yt_download_to_publish.py
│
├── assets/                    # README 静态资源
│   └── workbuddy-invite-poster.png
│
├── task_configs.json          # 任务类型定义
├── feishu_config.json         # 飞书聊天配置（含敏感，已 gitignore）
├── yt_config.json             # YouTube 下载配置（含敏感，已 gitignore）
├── sn.json                    # QR 快照脚本配置（含敏感，已 gitignore）
├── wf_publish.template.json   # 视频号发布工作流模板
├── youtube_cookies.txt        # YouTube 认证 cookies（已 gitignore）
│
├── requirements.txt
├── install_deps.bat           # 一键安装依赖（用本机 CPython 3.12 + --user）
├── setup.bat                  # 传统安装脚本
├── task_engine.bat            # 引擎启动脚本
├── feishu_chat.bat
├── update_cookies_batch.bat
│
├── 项目说明_业务视角.md         # 📖 业务文档
├── 设计说明文档.md
├── 数据字典.md
├── 项目依赖清单.md
│
└── README.md                  # ← 你正在看的文件
```

---

## ❓ 常见问题

<details>
<summary><b>Q: 视频号发布失败怎么办？</b></summary>

检查三件事：
1. `WeChatAppEx` 窗口是否正常（不能最小化到托盘）
2. 微信是否已登录
3. 发送 `重试任务 T-ID` 重新执行失败的阶段（已成功的不会重跑）
</details>

<details>
<summary><b>Q: YouTube 下载报 n-challenge 错误？</b></summary>

需要 `yt-dlp` + `nodejs` + `--remote-components ejs:github`：
```bash
yt-dlp --js-runtimes "node:你的node路径" --remote-components ejs:github ...
```
已写入 `yt_config.json` 的 `node_path` 字段。
</details>

<details>
<summary><b>Q: 默认 python 是 3.13 但 pywin32 装不进去？</b></summary>

`pywin32` 是 Windows-only，必须用本地系统 CPython 3.12 安装。
双击 `install_deps.bat` 即可（脚本写死了 3.12 路径，用 `--user` 安装）。
</details>

<details>
<summary><b>Q: 任务在「下载视频」阶段成功但「发布」阶段失败，重试会重新下载吗？</b></summary>

不会。`task_engine.py` 在重试时只重置 `failed`/`pending` 阶段；`success` 阶段跳过，连同其 post-adapter 也不跑。
下载阶段产出的 `video_filename` 已被持久化进 `tasks.json`，发布阶段照常能用。
</details>

更多问题请参考 [项目说明_业务视角.md](项目说明_业务视角.md)。

---

## 🛡️ 安全说明

- 所有含敏感信息的配置文件（`feishu_config.json` / `yt_config.json` / `sn.json` / `tasks.json` / `youtube_cookies.txt` / `.browser_profile/`）均已加入 `.gitignore`，**不会被提交到仓库**。
- 仓库里只保留脱敏示例：`*_config.example.json` / `sn.example.json`。
- 微信视频号发布目录 `WeChatAppEx/` 不入库（本地保留模板图片）。
- 所有文本文件统一以 **LF** 为规范换行（`.gitattributes` 已固化）。

---

## 📜 文档导航

- 📖 [项目说明_业务视角.md](项目说明_业务视角.md) — 业务场景、命令、状态、注意事项
- 📐 [设计说明文档.md](设计说明文档.md) — 系统设计
- 📊 [数据字典.md](数据字典.md) — 字段定义
- 📦 [项目依赖清单.md](项目依赖清单.md) — 完整依赖列表

---

## 🤝 致谢

- 这个项目就是用 **WorkBuddy**（你正在用的 AI 搭子）从 0 搭起来的。
- 飞书消息通信基于 `lark-cli`。
- YouTube 下载基于 `yt-dlp` 社区。

---

<div align="center">

### 🎁 还没注册 WorkBuddy？扫码领取 2000 积分

<a href="https://www.workbuddy.cn/events/invite?inviteCode=8ueyyequf3g24">
  <img src="assets/workbuddy-invite-poster.png" alt="WorkBuddy 邀请海报" width="320" />
</a>

**[👉 立即注册 WorkBuddy](https://www.workbuddy.cn/events/invite?inviteCode=8ueyyequf3g24)**

<sub>Made with 🐝 by WorkBuddy · 2026</sub>

</div>

# lark-cli 安装与配置指引（飞书官方 CLI）

> 适用：`'lark-cli' is not recognized as an internal or external command`，或 `feishu_send.py` 报"未找到 node.exe 或 lark-cli"。
> 实测环境：Windows 10 · Node 26.13.0 (WorkBuddy managed) · @larksuite/cli 1.0.98 · 2026-11-04
>
> 文中 `cli_xxx…`（App ID）、`oc_xxx…`（群 ID）、`ou_xxx…`（open_id）均为**脱敏占位符**。

---

## 一、先搞清楚它是怎么被找到的

`feishu_send.py:56-78` 的查找顺序（**决定了你必须装在哪**）：

| 顺位 | 查什么 | 命令 |
|---|---|---|
| 1 | PATH 上的 `lark-cli.cmd` / `.exe` / `lark-cli` | `where lark-cli` |
| 2 | `%USERPROFILE%\.workbuddy\binaries\node\cli-connector-packages\lark-cli.{cmd,exe,bat}` | 直接查文件 |
| 3 | 同目录 `node_modules\@larksuite\cli\scripts\run.js` | 直接查文件 |

第 2、3 顺位是 **WorkBuddy 托管 Node 的全局 prefix**，而且它**本来就在 PATH 里**。所以装到这里 = 一次满足全部三个条件，零改代码。

---

## 二、安装

### 2.1 确认 Node 可用

```bat
chcp 65001 >nul
node --version
npm --version
npm prefix -g
```

**期望**：能打印版本，`npm prefix -g` 输出 `C:\Users\hzc\.workbuddy\binaries\node\versions\26.13.0-1`。
若 `node` 不存在，说明 WorkBuddy 的托管 Node 没进 PATH —— 先解决这个，再往下。

### 2.2 安装（一条命令）

```bat
npm install -g --prefix "C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages" @larksuite/cli
```

> **`-g` 和 `--prefix` 缺一不可**
> - 只 `--prefix`（不带 `-g`）→ 当成局部安装，垫片落在 `node_modules\.bin\`，**PATH 里找不到**
> - 只 `-g`（不带 `--prefix`）→ 装到 `...\versions\26.13.0-1\`，会污染运行时目录，升级 Node 必丢

### 2.3 验证

```bat
where lark-cli
lark-cli --version
```

**期望**

```
C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages\lark-cli
C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages\lark-cli.cmd
lark-cli version 1.0.98
```

`where` 命中 `.cmd` 就成功了（`cmd.exe` 走的是 `.cmd`）。

> **不需要重开终端**：这个目录早就在 PATH 里，之前只是文件不存在。PATH 变量本身没变。

### 2.4 关于 npm 26 的 postinstall 拦截

安装日志里会出现：

```
npm warn install-scripts 1 package has install scripts not yet covered by allowScripts:
npm warn install-scripts   @larksuite/cli@1.0.98 (postinstall: node scripts/install.js)
```

**可以忽略**。`bin\lark-cli.exe`（48 MB）已随包落地；万一真缺，`scripts/run.js` 在首次运行时会自动补下（`run.js` 里 `if (!fs.existsSync(bin))` 分支）。

要显式放行：

```bat
npm install -g --allow-scripts=@larksuite/cli --prefix "C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages" @larksuite/cli
```

---

## 三、安装后的四层结构

```
① PATH 入口（垫片，不是程序）
C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages\
├── lark-cli        427 B   sh / Git Bash
├── lark-cli.cmd    344 B   cmd.exe  ← feishu_send.py 用这个
└── lark-cli.ps1    881 B   PowerShell

② 包本体（JS 层）
...\cli-connector-packages\node_modules\@larksuite\cli\
├── scripts\run.js          2 KB   ← 垫片指向它；也是 feishu_send.py 第 3 查找位
├── scripts\install.js             postinstall 下载器
├── scripts\install-wizard.js      `lark-cli install` 走这里
├── bin\lark-cli.exe        48 MB  ← 真正干活的二进制（Go 编译）
└── package.json                  version 1.0.98

③ 真实可执行
...\node_modules\@larksuite\cli\bin\lark-cli.exe

④ 配置与凭证（和安装目录无关）
C:\Users\hzc\.lark-cli\
├── config.json     appId / brand / userOpenId（appSecret 只存引用）
├── logs\  cache\  locks\  update-state.json
C:\Users\hzc\AppData\Local\lark-cli\keysigner\   ← 密钥托管目录
```

`lark-cli.cmd` 最后一行就是全部逻辑：

```bat
"%_prog%" "%dp0%\node_modules\@larksuite\cli\scripts\run.js" %*
```

**Node 只是启动器**，真正执行的是那个 48 MB 的 exe。

---

## 四、配置应用（拿到 App）

### 4.1 执行配置向导

```bat
lark-cli config init --new
```

它会**阻塞**，终端打出二维码 + 一条链接：

```
打开以下链接配置应用:
  https://open.feishu.cn/page/cli?user_code=XXXX-XXXX&lpv=1.0.98&from=cli
等待配置应用...
```

用**飞书 App 扫码**，或在已登录飞书的浏览器里打开该链接，按提示创建/选择自建应用。

成功输出：

```
OK: 应用配置成功! App ID: cli_xxxxxxxxxxxxxxxx
{"appId": "cli_xxxxxxxxxxxxxxxx", "appSecret": "****", "brand": "feishu"}
```

这一步完成的是**应用级凭证**（appId + appSecret），对应 **bot 身份**。

### 4.2 验证 bot 身份

```bat
lark-cli auth status --verify --json
```

**期望**（此时 user 还没登录）

```json
"identities": {
  "bot":  { "status": "ready", "verified": true, "openId": "ou_11111111111111111111111111111111" },
  "user": { "status": "missing", "message": "User identity: missing (no user logged in)" }
}
```

> `feishu_send.py` / `setup_check.py` 要求 **bot + user 双 ready**（`setup_check.py:638-653`），所以还得做第五步。

---

## 五、登录用户身份（user）

### 5.1 发起授权（推荐给 Agent/脚本用）

```bat
lark-cli auth login --no-wait --json --domain im
```

返回：

```json
{
  "device_code": "OIZ4...",
  "expires_in": 600,
  "verification_url": "https://accounts.feishu.cn/oauth/v1/device/verify?flow_id=...&user_code=DQWK-KGQG"
}
```

**10 分钟有效**。把 URL 给人，或生成二维码：

```bat
lark-cli auth qrcode "<verification_url>" -o "auth-qr.png"
```

### 5.2 用户授权完成后，用设备码收尾

```bat
lark-cli auth login --device-code "<device_code>"
```

**成功输出**

```
OK: 登录成功! 用户: 你的飞书账号名 (ou_22222222222222222222222222222222)
本次已成功授权：im:chat:read、im:message、im:message:readonly、im:resource、search:message ...
```

### 5.3 也可以直接阻塞式登录

```bat
lark-cli auth login --domain im
```

会一直阻塞到你在浏览器完成授权（最长 10 分钟）。人肉操作时更简单，脚本里别用。

### 5.4 ⚠️ `--domain im` **不包含**"以用户身份发消息"

授权清单里没有 `im:message.send_as_user`。所以：

```bat
lark-cli im +messages-send --chat-id oc_xxx --text hi --as user
```

会报：

```
missing_scope: missing required scope(s): im:message.send_as_user
```

**这是高危 scope，需单独申请**。若确需：

```bat
lark-cli auth login --scope "im:message.send_as_user" --no-wait --json
```

**否则就把 `feishu_config.json` 的 `默认身份` 保持 `bot`。**

---

## 六、让机器人真的能发消息（230002 坑）

### 现象

```bat
lark-cli im +messages-send --chat-id oc_xxx --text ping --as bot --json
```

```
"code": 230002, "message": "Bot/User can NOT be out of the chat."
```

### 原因

**机器人不在任何会话里。** 新装的应用只有身份，没有被拉进群/单聊。

```bat
lark-cli im +chat-list --as bot --json
```

返回空 → 确认此判断。

### 解法：以用户身份建群，同时把机器人邀进来

```bat
lark-cli im +chat-create --as user --name "任务引擎调试" --description "feishu-task-engine 调试用" --bots cli_xxxxxxxxxxxxxxxx --json
```

返回

```json
{ "ok": true, "data": { "chat_id": "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "name": "任务引擎调试" } }
```

确认机器人已入群：

```bat
lark-cli im +chat-members-list --chat-id oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx --as user --json
```

**期望** `"bot_total": 1` 且 `bots[0].app_id` 是你的 app。

再发一次就通了：

```bat
lark-cli im +messages-send --chat-id oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx --text "ping" --as bot --json
```

```
"message_id": "om_x100b6180c88134a0c1d220c1dd5bcbd"
```

---

## 七、验收清单

```bat
where lark-cli                                  :: 命中 cli-connector-packages\lark-cli.cmd
lark-cli --version                              :: 1.0.98
lark-cli auth status --verify --json            :: bot + user 都 ready / verified
lark-cli im +chat-list --json                   :: ok:true 且有 oc_ 开头的 chat_id
lark-cli im +messages-send --chat-id oc_... --text "ping" --as bot --json
```

最后接项目：

```bat
"%PY%" -X utf8 feishu_send.py --list
"%PY%" -X utf8 feishu_send.py "ping"
"%PY%" -X utf8 setup_check.py
```

---

## 八、凭证位置与迁移

| 文件 | 内容 | 能否直接拷贝 |
|---|---|---|
| `C:\Users\hzc\.lark-cli\config.json` | appId、brand、userOpenId、**appSecret 的引用** | ❌ 单独拷过去缺密钥 |
| `C:\Users\hzc\AppData\Local\lark-cli\keysigner\` | 密钥托管（DPoP/keysigner） | ⚠️ 与机器绑定，不建议 |
| token 缓存 | user access/refresh token | ❌ 会过期 |

**换机器正确做法**：在新机器上重新 `config init --new` + `auth login`，不要抄 config.json。

有效期参考（实测）：

```
expiresAt        : 2026-11-05T00:57:41+08:00   (2 小时)
refreshExpiresAt : 2026-11-11T22:57:41+08:00   (7 天)
```

refresh token 7 天不用就失效，届时 `auth status` 会变 `missing`，重跑 `auth login` 即可。

---

## 九、更新 / 卸载 / 重装

```bat
:: 更新到最新
npm install -g --prefix "C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages" @larksuite/cli@latest

:: 看当前版本 & 有没有新版
npm view @larksuite/cli version

:: 卸载（清安装，不动凭证）
npm uninstall -g --prefix "C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages" @larksuite/cli

:: 连凭证一起清（换账号时用）
rmdir /s /q "%USERPROFILE%\.lark-cli"
```

> WorkBuddy 大版本升级 Node 运行时**可能清掉 `cli-connector-packages`**。被清后重跑 2.2 那条命令即可，凭证在 `~/.lark-cli` 不受影响，不用重新扫码。

---

## 十、错误对照表

| 报错 | 原因 | 处理 |
|---|---|---|
| `'lark-cli' 不是内部或外部命令` | 没装，或装了没进 PATH | 按 2.2 装；用 `where lark-cli` 确认 |
| `"type":"config","subtype":"not_configured"` | 没跑过 `config init` | 第四步 |
| `User identity: missing` | 只做了 bot | 第五步 `auth login` |
| `230002 Bot/User can NOT be out of the chat` | 机器人不在会话 | 第六步建群邀请机器人 |
| `missing_scope: im:message.send_as_user` | user 身份发消息缺高危 scope | 保持 bot，或单独申请 scope |
| `device code 过期 / invalid_grant` | 链接超 10 分钟 | 重新 `--no-wait --json` 拿新码 |
| `未找到 node.exe 或 lark-cli` | `feishu_send.py` 三个查找位都空 | 装到 `cli-connector-packages`（第二节） |
| 中文输出乱码 | 控制台 GBK | `chcp 65001` + `set PYTHONUTF8=1` |

---

## 附：本机当前状态

| 项 | 值 |
|---|---|
| 包版本 | `@larksuite/cli@1.0.98` |
| 安装 prefix | `C:\Users\hzc\.workbuddy\binaries\node\cli-connector-packages`（49 MB） |
| App ID | `cli_xxxxxxxxxxxxxxxx`（brand: feishu） |
| bot openId | `ou_11111111111111111111111111111111` |
| user openId | `ou_22222222222222222222222222222222`（你的飞书账号名） |
| 授权域 | `im`（仅 chat/message 读、bot 发送；不含 send_as_user） |
| 默认调试群 | 任务引擎调试 `oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` |
| 发消息验证 | ✅ `om_x100b6180c88134a0c1d220c1dd5bcbd` |

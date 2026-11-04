# chrome-win64.zip 手工安装指引（Playwright Chromium）

> 适用：`python -m playwright install chromium` 报 **403 / not available in your location** 时的手工兜底方案。
> 实测环境：Windows 10 · playwright 1.64.1 (Python) · Chromium 156.0.8078.4 · 2026-11-04

---

## 一、为什么会失败

Playwright 的浏览器 CDN 在国内会被拒绝：

```
Error: Download failed: server returned code 403
body '... <Code>AccessDenied</Code> <Details>We're sorry, but this service
is not available in your location</Details>'
URL: https://cdn.playwright.dev/builds/cft/156.0.8078.4/win64/chrome-win64.zip
```

它是**按 IP 地区**拦的，重试 5 次结果一样（Playwright 内部就重试了 5 次才放弃）。

手工安装的本质：**自己把 zip 弄下来，解压到 Playwright 指定的位置，再补一个完成标记文件**。Playwright 只认路径和标记，不校验来源。

---

## 二、先确定"要装哪个版本"

版本不能随便挑，必须和 `playwright` 包自身声明的 revision 严格对应。

```bat
chcp 65001 >nul
"%PY%" -c "import playwright._repo_version as v;print(v.version)"
```

查浏览器清单：

```bat
"%PY%" -c "import json;d=json.load(open(r'C:\Users\hzc\AppData\Local\Programs\Python\Python312\Lib\site-packages\playwright\driver\package\browsers.json',encoding='utf-8'));[print(b['name'],b['revision'],b.get('browserVersion')) for b in d['browsers'] if 'chromium' in b['name']]"
```

本机实测输出：

```
chromium                 1248   156.0.8078.4
chromium-headless-shell  1248   156.0.8078.4
```

即：**revision `1248` ↔ Chrome for Testing `156.0.8078.4`**。

> revision 与 Chrome 版本是两套编号，别混。`chromium-1248` 是目录名，`156.0.8078.4` 是 zip 版本号。

---

## 三、下载源（实测可用性）

| 源 | URL 模板 | 实测 |
|---|---|---|
| **npmmirror / chrome-for-testing**（推荐） | `https://cdn.npmmirror.com/binaries/chrome-for-testing/<VER>/win64/chrome-win64.zip` | ✅ 200，207 MB，~1.7 MB/s |
| npmmirror / playwright | `https://cdn.npmmirror.com/binaries/playwright/builds/cft/<VER>/win64/chrome-win64.zip` | ✅ 200 |
| Google 官方 CfT | `https://storage.googleapis.com/chrome-for-testing-public/<VER>/win64/chrome-win64.zip` | ✅ 200（但国内慢） |
| registry.npmmirror 跳转 | `https://registry.npmmirror.com/-/binary/chrome-for-testing/...` | ⚠️ 302，需 `-L` |
| Playwright 官方 CDN | `https://cdn.playwright.dev/builds/cft/<VER>/win64/chrome-win64.zip` | ❌ 403 地区限制 |
| 微软镜像 | `https://playwright.download.prss.microsoft.com/dbazure/...` | ❌ 400 |

把 `<VER>` 换成 `156.0.8078.4`。

---

## 四、手工安装（CMD 逐步）

> **先设好三个变量**（本文所有命令都依赖它们，逐行粘，不要用 `&&` 串成一行 —— 见文末"CMD 变量提前展开"）
> ```bat
> chcp 65001 >nul
> set "PY=C:\Users\hzc\AppData\Local\Programs\Python\Python312\python.exe"
> set "VER=156.0.8078.4"
> set "REV=1248"
> set "STAGE=%TEMP%\cft-manual"
> ```

### 第 1 步　下载

```bat
mkdir "%STAGE%" 2>nul
curl -L --retry 5 -o "%STAGE%\chrome-win64.zip" "https://cdn.npmmirror.com/binaries/chrome-for-testing/%VER%/win64/chrome-win64.zip"
```

无 `curl` 就直接浏览器打开上面的 URL 下载，再手动放到 `%TEMP%\cft-manual\`。

**校验大小**：应为 **约 207,073,013 字节（197 MB）**。差太多说明下了一半。

```bat
dir "%STAGE%\chrome-win64.zip"
```

### 第 2 步　解压

```bat
C:\Windows\System32\tar.exe -xf "%STAGE%\chrome-win64.zip" -C "%STAGE%"
```

> **⚠️ 这里必须写全路径 `C:\Windows\System32\tar.exe`**
> 本机 PATH 上排在前面的 `tar` 是 WorkBuddy 自带 PortableGit 里的 **GNU tar 1.35**，它**不认 zip**，会直接报
> `tar: This does not look like a tar archive`。
> 只有系统自带的 `System32\tar.exe`（bsdtar 3.8.9）才能解 zip。这一点已实测确认。
>
> 备选：`powershell -NoProfile -Command "Expand-Archive -Path '%STAGE%\chrome-win64.zip' -DestinationPath '%STAGE%' -Force"`
> （大 zip 较慢，能用但不推荐）

### 第 3 步　放到 Playwright 认的位置

目标目录名规则（源码 `coreBundle.js:34051`）：

```
<browserName.replace(/-/g,'_') + "-" + revision>
```

`chromium` 不含横线 → 目录名就是 **`chromium-1248`**；可执行文件路径规则（`EXECUTABLE_PATHS["chromium"]["win-x64"]`）是 `<目录>\chrome-win64\chrome.exe`。

```bat
set "DEST=%LOCALAPPDATA%\ms-playwright\chromium-%REV%"
mkdir "%DEST%" 2>nul
xcopy "%STAGE%\chrome-win64" "%DEST%\chrome-win64\" /E /I /Y
```

### 第 4 步　写完成标记（关键，漏了就白装）

```bat
type nul > "%DEST%\INSTALLATION_COMPLETE"
```

Playwright 判定"已安装"的唯一依据是这个**空文件**（`coreBundle.js:33877`、`33950`）。没有它，即使文件齐全也会一直提示 *Please run playwright install*。

### 最终结构

```
%LOCALAPPDATA%\ms-playwright\
├── .links\                                  (playwright 自动维护，别删)
└── chromium-1248\
    ├── INSTALLATION_COMPLETE                 ← 空文件，0 字节
    └── chrome-win64\
        ├── chrome.exe                        (约 4.6 MB)
        ├── chrome.dll  icudtl.dat  v8_context_snapshot.bin
        ├── locales\  resources\  ...
        └── (共约 437 MB)
```

---

## 五、验证

### 5.1 路径是否被认到

```bat
"%PY%" -c "from playwright.sync_api import sync_playwright;s=sync_playwright().start();print(s.chromium.executable_path);s.stop()"
```

**期望**：`C:\Users\hzc\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe`

### 5.2 真正启动一次（有头 = 本项目 `update_cookies.py` 的模式）

```bat
"%PY%" -c "from playwright.sync_api import sync_playwright;s=sync_playwright().start();b=s.chromium.launch(headless=False);print('OK',b.version);b.close();s.stop()"
```

**期望**：弹出一个空白 Chrome 窗口后自动关闭，打印 `OK 156.0.8078.4`。

### 5.3 无头模式（可选，本项目不用）

```bat
"%PY%" -c "from playwright.sync_api import sync_playwright;s=sync_playwright().start();b=s.chromium.launch(headless=True);print('OK',b.version);b.close();s.stop()"
```

**会失败**，报：

```
Executable doesn't exist at ...\chromium_headless_shell-1248\chrome-headless-shell-win64\chrome-headless-shell.exe
```

原因：新版 Playwright 的 `headless=True` **不再复用 chromium**，而是单独要 `chromium-headless-shell`（`coreBundle.js:44796`）。

需要就再装一份，同样手工流程，zip 换成：

```
https://cdn.npmmirror.com/binaries/chrome-for-testing/156.0.8078.4/win64/chrome-headless-shell-win64.zip
```

落盘为 `%LOCALAPPDATA%\ms-playwright\chromium_headless_shell-1248\chrome-headless-shell-win64\` + `INSTALLATION_COMPLETE`（注意目录名里横线要变下划线）。

**本项目的 `update_cookies.py` 用 `headless=False`**（`update_cookies.py:89`），所以**不需要**装 headless-shell。

---

## 六、另一个更省事的办法：换下载源（不手工解压）

Playwright 支持改下载主机，配合 npmmirror 镜像：

```bat
set "PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright"
"%PY%" -m playwright install chromium
```

**注意**：该镜像只镜像了 `builds/cft/...` 路径，`ffmpeg`、`winldd` 等走 `dbazure` 前缀的资源仍会 404。所以这条适合"只缺 chromium"，需要完整套件时还是手工最稳。

先看它会下什么（不实际下载）：

```bat
"%PY%" -m playwright install --dry-run chromium
```

---

## 七、错误对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `403 AccessDenied ... not available in your location` | 官方 CDN 地区拦截 | 换 npmmirror 源手工装 |
| 每次都提示 `Please run playwright install` | 缺 `INSTALLATION_COMPLETE` | 第 4 步漏了，补空文件 |
| `Executable doesn't exist at ...chromium_headless_shell-1248...` | 用了 `headless=True` | 装 headless-shell，或改 `headless=False` |
| 直接双击/运行 `chrome.exe --version` 报 `Sandbox cannot access executable ... 拒绝访问 (0x5)` | 绕过 Playwright 直接跑，沙箱初始化异常 | 不影响 Playwright 调用，用 5.2 的方式验证即可 |
| 目录里文件齐但体积明显偏小（< 300 MB） | zip 没下完 | 删掉重下，核对 197 MB |
| `ms-playwright\__dirlock` 残留 | 上次安装被强杀 | 空目录，可安全删除 |
| `tar: This does not look like a tar archive` | PATH 上的 `tar` 是 GNU tar，不认 zip | 用全路径 `C:\Windows\System32\tar.exe`（bsdtar） |
| `'C:\...\python.exe' 不是内部或外部命令` | `set` 与 `%PY%` 在同一行 | 拆成两行，见第九节 |

---

## 八、清理与重装

只删 `chromium-1248` 目录不影响其他浏览器；重装就走第四步。

```bat
rmdir /s /q "%LOCALAPPDATA%\ms-playwright\chromium-1248"
```

下载缓存也别忘（一次能省 600 MB+）：

```bat
rmdir /s /q "%TEMP%\cft-manual"
rmdir /s /q "%TEMP%\playwright-download-*"
```

---

## 九、CMD 变量提前展开（踩过的坑）

CMD 解析**一整行**时就把 `%PY%` 替换成字面值，然后才执行该行里的 `set`。所以：

```bat
:: ❌ 失败：展开 %PY% 时 PY 还没赋值 → 'C:\...\python.exe' 不是内部或外部命令
set "PY=C:\Users\hzc\AppData\Local\Programs\Python\Python312\python.exe" && "%PY%" --version
```

```bat
:: ✅ 正确：两行，第二行解析时 PY 已有值
set "PY=C:\Users\hzc\AppData\Local\Programs\Python\Python312\python.exe"
"%PY%" --version
```

需要一行写完时用延迟展开：

```bat
cmd /v:on /c "set PY=C:\...\python.exe & !PY! --version"
```

本文全部命令按"一行一个"编排，**逐行粘贴**即可。

---

## 附：本机安装结果

| 项 | 值 |
|---|---|
| zip 大小 | 207,073,013 字节 |
| 安装体积 | 437 MB |
| 路径 | `C:\Users\hzc\AppData\Local\ms-playwright\chromium-1248\chrome-win64\chrome.exe` |
| 版本验证 | 有头启动 `OK 156.0.8078.4` |
| headless-shell | 未装（本项目不需要） |

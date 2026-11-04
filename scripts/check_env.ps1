<#
.SYNOPSIS
    feishu-task-engine 环境体检（只读，不安装任何东西）

.DESCRIPTION
    逐项检查运行 feishu-task-engine 所需的前提条件，输出 OK / WARN / FAIL 三态结论。
    本脚本不写仓库、不装依赖、不改系统环境变量；唯一的外部副作用是：
      - 在 %TEMP% 下写一个临时探测脚本（运行结束即删除）
      - 调用 lark-cli auth status / node --version 等只读命令

    退出码：
      0 = 全部通过
      1 = 存在 FAIL（环境不满足，不能启动）
      2 = 无 FAIL 但有 WARN（可以启动，部分功能会受限）

.PARAMETER Json
    以 JSON 输出结果，便于其他脚本消费（此时不打印彩色报表）。

.PARAMETER DryRun
    只打印将要检查的项目清单，不执行任何外部命令。

.PARAMETER PythonPath
    强制指定用哪个解释器做检查（默认自动挑选 3.12）。

.PARAMETER Online
    额外做一次网络连通性探测（pypi / github / Chromium 镜像）。

.EXAMPLE
    check-env.bat

.EXAMPLE
    check-env.bat -Json > env-report.json

.EXAMPLE
    check-env.bat -Online
#>
[CmdletBinding()]
param(
    [switch]$Json,
    [switch]$DryRun,
    [string]$PythonPath = "",
    [switch]$Online
)

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

# 让子进程输出按 UTF-8 解码（配合 check-env.bat 里的 chcp 65001）
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding           = [System.Text.Encoding]::UTF8
} catch { }

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $script:RepoRoot 'task_engine.py'))) {
    # 万一脚本被单独拷出去，退回到当前目录
    $script:RepoRoot = (Get-Location).Path
}

$script:Results = New-Object 'System.Collections.Generic.List[object]'
$script:LarkKind = 'none'
$script:LarkExe  = $null
$script:LarkRunJs = $null
$script:NodeExe  = $null

# ──────────────────────────────────────────────── 输出helper

function Add-R {
    param([string]$Area, [string]$Item, [string]$Status, [string]$Detail)
    $script:Results.Add([pscustomobject]@{
        Area   = $Area
        Item   = $Item
        Status = $Status
        Detail = $Detail
    })
}

function Show-Section {
    param([string]$Title)
    if ($Json) { return }
    Write-Host ""
    Write-Host ("── " + $Title + " " + ('─' * [Math]::Max(0, 62 - $Title.Length))) -ForegroundColor Cyan
}

function Show-R {
    param([object]$R)
    if ($Json) { return }
    switch ($R.Status) {
        'OK'   { $tag = ' OK '; $c = 'Green' }
        'WARN' { $tag = ' !! '; $c = 'Yellow' }
        'FAIL' { $tag = ' XX '; $c = 'Red' }
        default { $tag = ' -- '; $c = 'DarkGray' }
    }
    Write-Host ("[$tag] ") -ForegroundColor $c -NoNewline
    Write-Host ($R.Item) -NoNewline
    if ($R.Detail) { Write-Host ("  " + $R.Detail) -ForegroundColor DarkGray } else { Write-Host "" }
}

function Add-AndShow {
    param([string]$Area, [string]$Item, [string]$Status, [string]$Detail)
    Add-R -Area $Area -Item $Item -Status $Status -Detail $Detail
    Show-R -R $script:Results[$script:Results.Count - 1]
}

function Get-PyVersion {
    param([string]$Exe)
    try {
        $o = & $Exe -c "import sys;print('%d.%d.%d' % sys.version_info[:3])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $o) { return ($o | Select-Object -First 1).Trim() }
    } catch { }
    return $null
}

# ──────────────────────────────────────────────── DryRun

if ($DryRun) {
    Write-Host ""
    Write-Host "DryRun：以下项目会被检查，本次不执行任何外部命令" -ForegroundColor Yellow
    Write-Host ("仓库根目录: " + $script:RepoRoot)
    @(
        '1. 系统与会话（Windows 版本 / 交互式桌面）'
        '2. 解释器（候选清单 / 版本 / PATH 首位是否一致）'
        '3. Python 依赖（10 个包 + import 可用性）'
        '4. 外部工具（node / npm / yt-dlp / ffmpeg）'
        '5. lark-cli（三个查找顺位 / 版本 / 双身份授权）'
        '6. Chromium（browsers.json 期望版本 / 落盘 / 完成标记）'
        '7. 配置文件（feishu_config.json / yt_config.json）'
        '8. YouTube cookies'
        '9. 发布链路前提（WeChatAppEx 目录 / 11 张模板图 / 窗口）'
        '10. 静态校验（全部 .py 语法 + 根目录 JSON 合法性）'
    ) | ForEach-Object { Write-Host ("   - " + $_) }
    if ($Online) { Write-Host "   - 11. 网络连通性（已通过 -Online 开启）" }
    Write-Host ""
    exit 0
}

# ──────────────────────────────────────────────── 1. 系统

Show-Section '1. 系统与会话'
$os = [System.Environment]::OSVersion.Version
$isWin = ($env:OS -eq 'Windows_NT')
if ($isWin) {
    Add-AndShow 'sys' 'Windows' 'OK' ("{0}.{1} build {2} · {3}" -f $os.Major, $os.Minor, $os.Build, $env:PROCESSOR_ARCHITECTURE)
} else {
    Add-AndShow 'sys' 'Windows' 'FAIL' '非 Windows：run_workflow.py 依赖 win32gui，无法运行'
}
if ([System.Environment]::UserInteractive) {
    Add-AndShow 'sys' '交互式桌面会话' 'OK' '存在（GUI 自动化前提满足）'
} else {
    Add-AndShow 'sys' '交互式桌面会话' 'FAIL' '当前是非交互会话，pyautogui / 窗口操作会失败'
}

# ──────────────────────────────────────────────── 2. 解释器

Show-Section '2. 解释器'
$cands = New-Object 'System.Collections.Generic.List[object]'
$seen  = @{}

function Add-Cand {
    param([string]$Path, [string]$Source)
    if (-not $Path) { return }
    if (-not (Test-Path $Path)) { return }
    $key = $Path.ToLowerInvariant()
    if ($seen.ContainsKey($key)) { return }
    $seen[$key] = $true
    $v = Get-PyVersion -Exe $Path
    if ($v) { $cands.Add([pscustomobject]@{ Path = $Path; Source = $Source; Version = $v }) }
}

# PATH 上的（顺序即解析顺序）
$wherePy = @()
try { $wherePy = @(& where.exe python 2>$null | Where-Object { $_ } | ForEach-Object { ([string]$_).Trim() }) } catch { }
foreach ($p in $wherePy) { Add-Cand -Path $p -Source 'PATH' }

# 常见安装位置
foreach ($root in @("$env:LOCALAPPDATA\Programs\Python", 'C:\', "$env:ProgramFiles")) {
    if (-not (Test-Path $root)) { continue }
    Get-ChildItem -Path $root -Directory -Filter 'Python3*' -ErrorAction SilentlyContinue | ForEach-Object {
        Add-Cand -Path (Join-Path $_.FullName 'python.exe') -Source $_.Parent.Name
    }
}

$chosen = $null
if ($PythonPath) {
    if (Test-Path $PythonPath) {
        $v = Get-PyVersion -Exe $PythonPath
        if ($v) { $chosen = [pscustomobject]@{ Path = $PythonPath; Source = '-PythonPath'; Version = $v } }
    }
    if (-not $chosen) { Add-AndShow 'py' '指定的解释器' 'FAIL' ("-PythonPath 不可用: " + $PythonPath) }
}
if (-not $chosen) {
    $chosen = $cands | Where-Object { $_.Version -like '3.12.*' } | Select-Object -First 1
}
if (-not $chosen) {
    $chosen = $cands | Where-Object { $_.Version -match '^3\.(1[2-9]|[2-9][0-9])\.' } | Select-Object -First 1
}

if ($cands.Count -eq 0) {
    Add-AndShow 'py' '可用解释器' 'FAIL' '未找到任何 python.exe（需要 3.12+）'
} else {
    $list = ($cands | ForEach-Object { $_.Version + ' @ ' + $_.Path }) -join ' ; '
    Add-AndShow 'py' ('候选解释器 x' + $cands.Count) 'OK' $list
}

if ($chosen) {
    $ver = $chosen.Version
    if ($ver -like '3.12.*') {
        Add-AndShow 'py' '选定解释器' 'OK' ($ver + '  ' + $chosen.Path)
    } elseif ($ver -match '^3\.(1[3-9]|[2-9][0-9])\.') {
        Add-AndShow 'py' '选定解释器' 'WARN' ($ver + '  ' + $chosen.Path + '  （未在 3.13 上验证过 pywin32）')
    } else {
        Add-AndShow 'py' '选定解释器' 'FAIL' ($ver + ' < 3.12，不满足要求')
        $chosen = $null
    }
}

if ($chosen) {
    # PATH 首位是否就是选定的这个（决定 task_configs.json 里字面 "python" 落到哪）
    $firstOnPath = $null
    if ($wherePy -and $wherePy.Count -gt 0) { $firstOnPath = [string]$wherePy[0] }
    if ($firstOnPath) {
        if ($firstOnPath.ToLowerInvariant() -eq $chosen.Path.ToLowerInvariant()) {
            Add-AndShow 'py' 'PATH 首位 python' 'OK' '与选定解释器一致'
        } else {
            $fv = Get-PyVersion -Exe $firstOnPath
            Add-AndShow 'py' 'PATH 首位 python' 'WARN' ($fv + ' @ ' + $firstOnPath + '  ≠ 选定解释器；启动引擎前需把选中版本前置到 PATH')
        }
    } else {
        Add-AndShow 'py' 'PATH 首位 python' 'FAIL' 'PATH 上找不到 python，子进程调用会失败'
    }
}

# ──────────────────────────────────────────────── 3-4. Python 侧探测（一个临时脚本拿全部结果）

$probe = $null
if ($chosen) {
    Show-Section '3. Python 依赖'
    $probeSrc = @'
import json, os, sys, glob, ast

out = {}
out["executable"] = sys.executable
out["version"] = "%d.%d.%d" % sys.version_info[:3]

spec = [
    ("win32gui", "pywin32"), ("pyautogui", "PyAutoGUI"), ("cv2", "opencv-python"),
    ("PIL", "Pillow"), ("psutil", "psutil"), ("pyperclip", "pyperclip"),
    ("playwright", "playwright"), ("yt_dlp", "yt-dlp"),
    ("imageio_ffmpeg", "imageio-ffmpeg"), ("socks", "PySocks"),
]
deps = []
try:
    import importlib.util
    import importlib.metadata as md
except Exception:
    importlib = None
    md = None
for mod, pkg in spec:
    item = {"mod": mod, "pkg": pkg, "version": None, "importable": False}
    try:
        item["importable"] = importlib.util.find_spec(mod) is not None
    except Exception:
        item["importable"] = False
    try:
        item["version"] = md.version(pkg)
    except Exception:
        pass
    deps.append(item)
out["deps"] = deps

try:
    import imageio_ffmpeg
    out["ffmpeg"] = imageio_ffmpeg.get_ffmpeg_exe()
except Exception:
    out["ffmpeg"] = None

try:
    from yt_dlp.version import __version__ as ytv
    out["yt_dlp"] = ytv
except Exception:
    out["yt_dlp"] = None

try:
    import playwright
    out["playwright_dir"] = os.path.dirname(playwright.__file__)
except Exception:
    out["playwright_dir"] = None

try:
    import win32gui, win32process, psutil
    targets = ("wechatappex.exe", "wechat.exe", "weixin.exe")
    titles = []
    def _cb(h, _):
        try:
            if not win32gui.IsWindowVisible(h):
                return
            _t, pid = win32process.GetWindowThreadProcessId(h)
            try:
                pname = psutil.Process(pid).name().lower()
            except Exception:
                pname = ""
            if pname in targets:
                t = win32gui.GetWindowText(h) or ""
                c = win32gui.GetClassName(h) or ""
                titles.append(pname + " | " + c + " | " + t)
        except Exception:
            pass
    win32gui.EnumWindows(_cb, None)
    out["wechat_windows"] = titles
except Exception:
    out["wechat_windows"] = None

repo = sys.argv[1]
ok_py, bad_py = 0, []
for f in glob.glob(os.path.join(repo, "**", "*.py"), recursive=True):
    try:
        fh = open(f, "rb")
        src = fh.read()
        fh.close()
        ast.parse(src.decode("utf-8"), f)
        ok_py += 1
    except Exception as e:
        bad_py.append(os.path.basename(f) + ": " + str(e)[:80])
ok_json, bad_json = 0, []
for f in sorted(glob.glob(os.path.join(repo, "*.json"))):
    try:
        fh = open(f, "rb")
        json.loads(fh.read().decode("utf-8"))
        fh.close()
        ok_json += 1
    except Exception as e:
        bad_json.append(os.path.basename(f) + ": " + str(e)[:80])
out["py_ok"], out["py_bad"] = ok_py, bad_py
out["json_ok"], out["json_bad"] = ok_json, bad_json

sys.stdout.write(json.dumps(out, ensure_ascii=True))
'@
    $tmpPy = Join-Path $env:TEMP ('fte_probe_' + [guid]::NewGuid().ToString('N').Substring(0, 8) + '.py')
    try {
        Set-Content -Path $tmpPy -Value $probeSrc -Encoding UTF8
        $raw = & $chosen.Path $tmpPy $script:RepoRoot 2>&1 | Out-String
        $probe = $raw | ConvertFrom-Json
    } catch {
        $probe = $null
    } finally {
        if (Test-Path $tmpPy) { Remove-Item $tmpPy -Force -ErrorAction SilentlyContinue }
    }

    if (-not $probe) {
        Add-AndShow 'py' '依赖探测' 'FAIL' '探测脚本执行失败（解释器可能损坏）'
    } else {
        $missing = @($probe.deps | Where-Object { -not $_.importable })
        $broken  = @($probe.deps | Where-Object { $_.importable -and -not $_.version })
        foreach ($d in $probe.deps) {
            if (-not $d.importable) {
                Add-AndShow 'deps' $d.pkg 'FAIL' ('未安装或无法导入（import ' + $d.mod + '）')
            } elseif (-not $d.version) {
                Add-AndShow 'deps' $d.pkg 'WARN' ('可导入但元数据缺失')
            } else {
                Add-AndShow 'deps' $d.pkg 'OK' ('v' + $d.version)
            }
        }

        Show-Section '4. 外部工具'
        if ($probe.yt_dlp) {
            Add-AndShow 'tool' 'yt-dlp' 'OK' ('v' + $probe.yt_dlp + '（python 模块）')
        } else {
            Add-AndShow 'tool' 'yt-dlp' 'FAIL' '未安装：pip install yt-dlp'
        }
        if ($probe.ffmpeg) {
            Add-AndShow 'tool' 'ffmpeg' 'OK' $probe.ffmpeg
        } else {
            Add-AndShow 'tool' 'ffmpeg' 'FAIL' 'imageio-ffmpeg 不可用：pip install imageio-ffmpeg'
        }
    }
}

# node / npm
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) {
    $nv = (& node --version 2>$null | Select-Object -First 1)
    $script:NodeExe = $nodeCmd.Source
    Add-AndShow 'tool' 'node' 'OK' ('v' + ($nv -replace '^v', '') + '  ' + $nodeCmd.Source)
} else {
    Add-AndShow 'tool' 'node' 'FAIL' '不在 PATH（lark-cli 与 yt-dlp 的 JS runtime 都需要）'
}
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if ($npmCmd) {
    $reg = (& npm config get registry 2>$null | Select-Object -First 1)
    Add-AndShow 'tool' 'npm registry' 'OK' $reg
} else {
    Add-AndShow 'tool' 'npm' 'WARN' '不在 PATH（仅在需要安装 lark-cli 时才必须）'
}

# ──────────────────────────────────────────────── 5. lark-cli

Show-Section '5. lark-cli'
$larkFound = $null
$lc = Get-Command lark-cli -ErrorAction SilentlyContinue
if ($lc) {
    $larkFound = $lc.Source
    # PowerShell 会优先解析到 .ps1 垫片；统一用 .cmd 更贴近 feishu_send.py 的实际调用方式
    if ($larkFound -like '*.ps1') {
        $cmdSibling = [System.IO.Path]::ChangeExtension($larkFound, '.cmd')
        if (Test-Path $cmdSibling) { $larkFound = $cmdSibling }
    }
}
$managedBase = Join-Path $env:USERPROFILE '.workbuddy\binaries\node\cli-connector-packages'
if (-not $larkFound) {
    foreach ($ext in @('.cmd', '.exe', '.bat', '')) {
        $c = Join-Path $managedBase ('lark-cli' + $ext)
        if (Test-Path $c) { $larkFound = $c; break }
    }
}
$runJs = Join-Path $managedBase 'node_modules\@larksuite\cli\scripts\run.js'
if ($larkFound) {
    $script:LarkKind = 'exe'
    $script:LarkExe  = $larkFound
    $lv = (& $larkFound --version 2>$null | Select-Object -First 1)
    Add-AndShow 'lark' 'lark-cli' 'OK' (($lv -replace '\s+', ' ').Trim() + '  ' + $larkFound)
} elseif ((Test-Path $runJs) -and $script:NodeExe) {
    $script:LarkKind  = 'runjs'
    $script:LarkRunJs = $runJs
    Add-AndShow 'lark' 'lark-cli' 'WARN' ('未生成 PATH 垫片，回退用 node run.js：' + $runJs)
} else {
    Add-AndShow 'lark' 'lark-cli' 'FAIL' '未安装：npm install -g --prefix "<cli-connector-packages>" @larksuite/cli'
}

function Invoke-Lark {
    param([string[]]$LarkArgs)
    if ($script:LarkKind -eq 'runjs') {
        return (& $script:NodeExe $script:LarkRunJs @LarkArgs 2>&1 | Out-String)
    } elseif ($script:LarkKind -eq 'exe') {
        return (& $script:LarkExe @LarkArgs 2>&1 | Out-String)
    }
    return ''
}

if ($script:LarkKind -ne 'none') {
    $authRaw = Invoke-Lark @('auth', 'status', '--verify', '--json')
    $auth = $null
    try { $auth = $authRaw | ConvertFrom-Json } catch { $auth = $null }
    if (-not $auth) {
        Add-AndShow 'lark' 'auth status' 'FAIL' '返回内容不是合法 JSON（可能未配置应用）'
    } else {
        $ident = $null
        if ($auth.PSObject.Properties.Name -contains 'identities') {
            $ident = $auth.identities
        } elseif (($auth.PSObject.Properties.Name -contains 'data') -and ($auth.data.PSObject.Properties.Name -contains 'identities')) {
            $ident = $auth.data.identities
        }
        if ($ident) {
            foreach ($role in @('bot', 'user')) {
                $node = $ident.$role
                if (-not $node) {
                    Add-AndShow 'lark' ($role + ' 身份') 'FAIL' 'missing'
                } else {
                    $st = [string]$node.status
                    if ($st -eq 'ready') {
                        $extra = ''
                        if ($node.openId) { $extra = '  ' + $node.openId }
                        Add-AndShow 'lark' ($role + ' 身份') 'OK' ($st + $extra)
                    } else {
                        $msg = ''
                        if ($node.message) { $msg = '  ' + $node.message }
                        Add-AndShow 'lark' ($role + ' 身份') 'FAIL' ($st + $msg)
                    }
                }
            }
        } else {
            Add-AndShow 'lark' 'identities' 'FAIL' 'JSON 中没有 identities 字段'
        }
    }
}

# ──────────────────────────────────────────────── 6. Chromium

Show-Section '6. Chromium（update_cookies.py 需要）'
$expRev, $expVer, $expSrc = $null, $null, $null
if ($probe -and $probe.playwright_dir) {
    $bj = Join-Path $probe.playwright_dir 'driver\package\browsers.json'
    if (Test-Path $bj) {
        try {
            $b = Get-Content -Raw -Encoding UTF8 $bj | ConvertFrom-Json
            $cr = $b.browsers | Where-Object { $_.name -eq 'chromium' } | Select-Object -First 1
            if ($cr) { $expRev = [string]$cr.revision; $expVer = [string]$cr.browserVersion; $expSrc = $bj }
        } catch { }
    }
}
$msDir = Join-Path $env:LOCALAPPDATA 'ms-playwright'
if ($expRev) {
    $dir   = Join-Path $msDir ('chromium-' + $expRev)
    $exe   = Join-Path $dir 'chrome-win64\chrome.exe'
    $mark  = Join-Path $dir 'INSTALLATION_COMPLETE'
    if ((Test-Path $exe) -and (Test-Path $mark)) {
        Add-AndShow 'cr' ('chromium-' + $expRev) 'OK' ($expVer + '  ' + $exe)
    } elseif (Test-Path $exe) {
        Add-AndShow 'cr' ('chromium-' + $expRev) 'WARN' ('有 chrome.exe 但缺 INSTALLATION_COMPLETE，playwright 仍视为未安装：' + $dir)
    } else {
        Add-AndShow 'cr' ('chromium-' + $expRev) 'FAIL' ('缺 ' + $exe + '（需要 ' + $expVer + '，参见 setup-docs/02）')
    }
    $hs = Join-Path $msDir ('chromium_headless_shell-' + $expRev)
    if (Test-Path $hs) {
        Add-AndShow 'cr' 'headless shell' 'OK' '已存在（本项目用有头模式，非必需）'
    } else {
        Add-AndShow 'cr' 'headless shell' 'SKIP' '未安装；只有 headless=True 才需要'
    }
} else {
    if (Test-Path $msDir) {
        $got = @(Get-ChildItem $msDir -Directory -Filter 'chromium-*' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
        Add-AndShow 'cr' 'chromium' 'WARN' ('无法从 playwright 读取期望版本；现有: ' + ($got -join ', '))
    } else {
        Add-AndShow 'cr' 'chromium' 'FAIL' ('playwright 未安装或 ms-playwright 目录不存在（' + $msDir + '）')
    }
}

# ──────────────────────────────────────────────── 7. 配置文件

Show-Section '7. 配置文件'
$fcPath = Join-Path $script:RepoRoot 'feishu_config.json'
if (-not (Test-Path $fcPath)) {
    Add-AndShow 'cfg' 'feishu_config.json' 'FAIL' '不存在：先运行 feishu_send.py --sync'
} else {
    try {
        $fc = Get-Content -Raw -Encoding UTF8 $fcPath | ConvertFrom-Json
        $chats = @($fc.'聊天列表')
        $dname = [string]$fc.'默认聊天名称'
        $real  = @($chats | Where-Object { $_.chat_id -and ($_.chat_id -notlike 'oc_xxxx*') })
        if ($real.Count -gt 0) {
            Add-AndShow 'cfg' 'feishu_config.json' 'OK' ($real.Count.ToString() + ' 个真实会话')
        } else {
            Add-AndShow 'cfg' 'feishu_config.json' 'FAIL' '只有占位符 chat_id，需 --sync 获取真实会话'
        }
        if ($dname -and ($chats | Where-Object { $_.'名称' -eq $dname })) {
            Add-AndShow 'cfg' '默认聊天' 'OK' $dname
        } else {
            Add-AndShow 'cfg' '默认聊天' 'FAIL' ('未设置或名称不存在: ' + $dname)
        }
    } catch {
        Add-AndShow 'cfg' 'feishu_config.json' 'FAIL' 'JSON 解析失败'
    }
}

$ytPath = Join-Path $script:RepoRoot 'yt_config.json'
if (-not (Test-Path $ytPath)) {
    Add-AndShow 'cfg' 'yt_config.json' 'FAIL' '不存在：cp yt_config.example.json yt_config.json 后按需修改'
} else {
    try {
        $yt = Get-Content -Raw -Encoding UTF8 $ytPath | ConvertFrom-Json
        $keys = ($yt.PSObject.Properties.Name) -join ', '
        Add-AndShow 'cfg' 'yt_config.json' 'OK' ('键: ' + $keys)
    } catch {
        Add-AndShow 'cfg' 'yt_config.json' 'FAIL' 'JSON 解析失败'
    }
}

# ──────────────────────────────────────────────── 8. cookies

Show-Section '8. YouTube cookies'
$ck = Join-Path $script:RepoRoot 'youtube_cookies.txt'
if (Test-Path $ck) {
    $kb = [math]::Round((Get-Item $ck).Length / 1KB, 1)
    Add-AndShow 'ck' 'youtube_cookies.txt' 'OK' ($kb.ToString() + ' KB')
} else {
    Add-AndShow 'ck' 'youtube_cookies.txt' 'WARN' '缺失：YouTube 会要求人机验证，用 update_cookies.py 生成'
}

# ──────────────────────────────────────────────── 9. 发布链路

Show-Section '9. 发布链路前提（微信视频号）'
$wfPath = Join-Path $script:RepoRoot 'wf_publish.template.json'
$procName = 'WeChatAppEx'
$tplNames = @()
if (Test-Path $wfPath) {
    try {
        $wf = Get-Content -Raw -Encoding UTF8 $wfPath | ConvertFrom-Json
        if ($wf.'进程名') { $procName = [string]$wf.'进程名' }
        foreach ($step in @($wf.'工作流')) {
            $p = $step.'点位图'
            if ($p -and ($p -is [string])) { $tplNames += $p }
            $r = $step.'必要点位'
            if ($r -is [array]) { foreach ($x in $r) { if ($x -is [string] -and $x -match '\.png$') { $tplNames += $x } } }
        }
        $tplNames = $tplNames | Select-Object -Unique
    } catch { }
}
if ($tplNames.Count -eq 0) {
    Add-AndShow 'pub' '工作流模板清单' 'WARN' '无法从 wf_publish.template.json 解析出模板名'
} else {
    $tplDir = Join-Path $script:RepoRoot $procName
    $have = @()
    $miss = @()
    foreach ($n in $tplNames) {
        if (Test-Path (Join-Path $tplDir $n)) { $have += $n } else { $miss += $n }
    }
    if ($miss.Count -eq 0) {
        Add-AndShow 'pub' ('模板图 ' + $tplNames.Count + ' 张') 'OK' ('全部就位于 ' + $tplDir)
    } else {
        Add-AndShow 'pub' ('模板图 ' + $tplNames.Count + ' 张') 'WARN' ($have.Count.ToString() + ' 有 / ' + $miss.Count + ' 缺: ' + ($miss -join ', '))
    }
    if (-not (Test-Path $tplDir)) {
        Add-AndShow 'pub' ($procName + ' 目录') 'WARN' '不存在：mkdir 后把模板截图放进去'
    } else {
        Add-AndShow 'pub' ($procName + ' 目录') 'OK' $tplDir
    }
}
$procNames = @($procName, 'WeChat', 'Weixin')
$procHits = @()
foreach ($pn in $procNames) {
    $pp = @(Get-Process -Name $pn -ErrorAction SilentlyContinue)
    if ($pp.Count -gt 0) { $procHits += ($pn + ' x' + $pp.Count) }
}
if ($procHits.Count -gt 0) {
    Add-AndShow 'pub' '微信进程' 'OK' ($procHits -join ', ')
} else {
    Add-AndShow 'pub' '微信进程' 'WARN' '未运行（发布时必须已登录并保持窗口）'
}
if ($probe -and $null -ne $probe.wechat_windows) {
    $w = @($probe.wechat_windows)
    $clientWins = @($w | Where-Object { $_ -match '^(wechat|weixin)\.exe' })
    $appWins    = @($w | Where-Object { $_ -match '^wechatappex\.exe' })
    if ($w.Count -eq 0) {
        Add-AndShow 'pub' '微信窗口' 'WARN' '未发现可见窗口（最小化/未登录都会导致匹配失败）'
    } elseif ($clientWins.Count -gt 0) {
        Add-AndShow 'pub' '微信主窗口' 'OK' ([string]$clientWins[0])
    }
    if ($appWins.Count -gt 0) {
        Add-AndShow 'pub' '视频号助手窗口' 'OK' ([string]$appWins[0])
    } else {
        Add-AndShow 'pub' '视频号助手窗口' 'WARN' '未发现 WeChatAppEx 窗口：需在微信里打开「视频号助手」页面后保持窗口可见'
    }
}

# ──────────────────────────────────────────────── 10. 静态校验

Show-Section '10. 静态校验'
if ($probe) {
    if ($probe.py_bad.Count -eq 0) {
        Add-AndShow 'static' ('Python 语法 x' + $probe.py_ok) 'OK' '全部可解析'
    } else {
        Add-AndShow 'static' 'Python 语法' 'FAIL' (($probe.py_bad) -join ' ; ')
    }
    if ($probe.json_bad.Count -eq 0) {
        Add-AndShow 'static' ('根目录 JSON x' + $probe.json_ok) 'OK' '全部合法'
    } else {
        Add-AndShow 'static' '根目录 JSON' 'FAIL' (($probe.json_bad) -join ' ; ')
    }
} else {
    Add-AndShow 'static' '静态校验' 'SKIP' '依赖探测未成功，跳过'
}

# ──────────────────────────────────────────────── 11. 网络（可选）

if ($Online) {
    Show-Section '11. 网络连通性'
    $targets = @(
        @{ N = 'pypi.org';       U = 'https://pypi.org/simple/' },
        @{ N = 'mirrors.aliyun'; U = 'https://mirrors.aliyun.com/pypi/simple/' },
        @{ N = 'github.com';     U = 'https://github.com' },
        @{ N = 'Chromium 镜像';  U = 'https://cdn.npmmirror.com/binaries/chrome-for-testing/' }
    )
    foreach ($t in $targets) {
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        $code = 0
        try {
            $resp = Invoke-WebRequest -Uri $t.U -Method Head -TimeoutSec 8 -UseBasicParsing -ErrorAction Stop
            $code = [int]$resp.StatusCode
        } catch {
            if ($_.Exception.Response) { $code = [int]$_.Exception.Response.StatusCode } else { $code = 0 }
        }
        $sw.Stop()
        if ($code -ge 200 -and $code -lt 400) {
            Add-AndShow 'net' $t.N 'OK' ($code.ToString() + '  ' + $sw.ElapsedMilliseconds + 'ms')
        } else {
            Add-AndShow 'net' $t.N 'WARN' ('HTTP ' + $code + '  ' + $sw.ElapsedMilliseconds + 'ms')
        }
    }
}

# ──────────────────────────────────────────────── 汇总

$fails = @($script:Results | Where-Object { $_.Status -eq 'FAIL' })
$warns = @($script:Results | Where-Object { $_.Status -eq 'WARN' })
$oks   = @($script:Results | Where-Object { $_.Status -eq 'OK' })
$skips = @($script:Results | Where-Object { $_.Status -eq 'SKIP' })

if ($fails.Count -gt 0) { $exit = 1 } elseif ($warns.Count -gt 0) { $exit = 2 } else { $exit = 0 }

if ($Json) {
    $obj = [pscustomobject]@{
        repoPath = $script:RepoRoot
        generated = (Get-Date).ToString('s')
        interpreter = $(if ($chosen) { $chosen.Path } else { $null })
        summary = [pscustomobject]@{
            ok = $oks.Count; warn = $warns.Count; fail = $fails.Count; skip = $skips.Count; exitCode = $exit
        }
        results = $script:Results
    }
    $jsonText = $obj | ConvertTo-Json -Depth 6
    # 统一转成纯 ASCII（非 ASCII 字符转 \uXXXX），避免调用方代码页不匹配导致 JSON 损坏
    $sb = New-Object System.Text.StringBuilder
    foreach ($ch in $jsonText.ToCharArray()) {
        if ([int]$ch -lt 128) {
            [void]$sb.Append($ch)
        } else {
            [void]$sb.Append(('\u{0:x4}' -f [int]$ch))
        }
    }
    [Console]::Out.Write($sb.ToString() + "`r`n")
    exit $exit
}

Write-Host ""
Write-Host ('=' * 70) -ForegroundColor DarkGray
Write-Host ("汇总: {0} OK / {1} WARN / {2} FAIL / {3} SKIP" -f $oks.Count, $warns.Count, $fails.Count, $skips.Count) -ForegroundColor White
if ($fails.Count -gt 0) {
    Write-Host ""
    Write-Host "必须解决（FAIL）：" -ForegroundColor Red
    $fails | ForEach-Object { Write-Host ("  · " + $_.Item + " — " + $_.Detail) -ForegroundColor Red }
}
if ($warns.Count -gt 0) {
    Write-Host ""
    Write-Host "建议处理（WARN）：" -ForegroundColor Yellow
    $warns | ForEach-Object { Write-Host ("  · " + $_.Item + " — " + $_.Detail) -ForegroundColor Yellow }
}
Write-Host ""
switch ($exit) {
    0 { Write-Host "结论: 环境就绪，可以启动 task_engine.py" -ForegroundColor Green }
    1 { Write-Host "结论: 环境不满足，先解决上面的 FAIL 项（详见 setup-docs/01）" -ForegroundColor Red }
    2 { Write-Host "结论: 可以启动，但有 WARN 项会导致部分功能不可用（详见 setup-docs/01）" -ForegroundColor Yellow }
}
Write-Host ""

exit $exit

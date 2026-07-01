"""
setup_check.py — 飞书任务引擎 · 环境检查与配置引导工具

检查项：
  1. lark-cli 安装 → 授权登录 → feishu_config.json 配置
  2. yt-dlp / node / ffmpeg 安装状态
  3. yt_config.json 自动检测与补齐（含代理配置）

用法:
  python setup_check.py
"""
import os
import sys
import json
import copy
import shutil
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# ─── 显示样式 ────────────────────────────────────────
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"

# Windows GBK 终端兼容：使用 ASCII 符号
PASS = "V"
WARN_SYM = "!"
FAIL_SYM = "X"
INFO_SYM = "i"

def ok(msg):
    print(f"  [{GREEN}{PASS}{RESET}] {msg}")

def warn(msg):
    print(f"  [{YELLOW}{WARN_SYM}{RESET}] {msg}")

def fail(msg):
    print(f"  [{RED}{FAIL_SYM}{RESET}] {msg}")

def info(msg):
    print(f"  [{CYAN}{INFO_SYM}{RESET}] {msg}")

def section(title):
    print(f"\n{BOLD}============= {title} ============={RESET}\n")


# ─── 工具函数 ────────────────────────────────────────

def run_cmd(cmd, timeout=15):
    """运行命令并返回 (returncode, stdout, stderr)"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, timeout=timeout, shell=True
        )
        out = r.stdout.decode("utf-8", errors="replace").strip()
        err = r.stderr.decode("utf-8", errors="replace").strip()
        return r.returncode, out, err
    except FileNotFoundError:
        return -1, "", "command not found"
    except subprocess.TimeoutExpired:
        return -2, "", "timeout"


def input_optional(prompt, default=None):
    """带默认值的输入"""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    try:
        val = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default or ""
    return val if val else default


def input_yesno(prompt, default="y"):
    """是/否 询问"""
    hint = "(Y/n)" if default == "y" else "(y/N)"
    try:
        val = input(f"{prompt} {hint} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default == "y"
    if not val:
        return default == "y"
    return val.startswith("y")


# ══════════════════════════════════════════════════════
# 阶段 1：lark-cli
# ══════════════════════════════════════════════════════

def check_lark_cli():
    """检查 lark-cli 是否可执行"""
    # 复用 feishu_send.py 的查找策略
    for name in ["lark-cli.cmd", "lark-cli.exe", "lark-cli"]:
        rc, out, _ = run_cmd(f"where {name}")
        if rc == 0 and out:
            path = out.splitlines()[0]
            if path.endswith((".cmd", ".exe", ".bat")):
                return path

    # WorkBuddy managed 路径
    base = Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages"
    for ext in [".cmd", ".exe", ".bat", ""]:
        candidate = base / f"lark-cli{ext}"
        if candidate.exists() and ext and candidate.suffix:
            return str(candidate)

    # 回退：看看 node + run.js 能不能用
    node_exe = check_node(quiet=True)
    if node_exe:
        run_js = base / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
        if run_js.exists():
            return f"{node_exe} {run_js} (via node run.js)"
    return None


def check_lark_auth():
    """检查 lark-cli 登录状态"""
    # 先用 node run.js 方式执行 auth status
    node_exe = check_node(quiet=True)
    if node_exe:
        run_js = Path.home() / ".workbuddy" / "binaries" / "node" / \
            "cli-connector-packages" / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
        if run_js.exists():
            rc, out, _ = run_cmd(f'"{node_exe}" "{run_js}" auth status --verify --json')
            if rc == 0 and out:
                try:
                    data = json.loads(out)
                    return data
                except json.JSONDecodeError:
                    pass

    # 回退：用 lark-cli 调用
    rc, out, _ = run_cmd("lark-cli auth status --verify --json")
    if rc == 0 and out:
        try:
            data = json.loads(out)
            return data
        except json.JSONDecodeError:
            pass
    return None


def run_lark_login():
    """引导用户完成飞书登录（使用交互模式，最稳定）"""
    print()
    info("启动飞书授权...\n")

    # 先用 lark-cli 命令，不行就尝试 node run.js
    cmd = None
    rc, _, _ = run_cmd("lark-cli --version")
    if rc == 0:
        cmd = "lark-cli auth login --recommend"
    else:
        node_exe = check_node(quiet=True)
        if node_exe:
            run_js = Path.home() / ".workbuddy" / "binaries" / "node" / \
                "cli-connector-packages" / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
            if run_js.exists():
                cmd = f'"{node_exe}" "{run_js}" auth login'

    if not cmd:
        fail("无法找到 lark-cli 可执行文件，请先安装 Node.js 后执行: npm install -g @larksuite/cli")
        return False

    info("请在打开的交互界面中：\n"
         "  1. 方向键选择权限域（至少勾选 im）\n"
         "  2. 按 Enter 确认\n"
         "  3. 用飞书扫码或浏览器打开链接完成授权\n")

    ret = os.system(cmd)

    # 等待用户确认后重新检查授权状态
    input("\n  授权完成后，按 Enter 键继续...")

    # 重新检查授权状态
    auth_data = check_lark_auth()
    if auth_data:
        ids = auth_data.get("identities", {})
        bot_ok = ids.get("bot", {}).get("status") == "ready"
        user_ok = ids.get("user", {}).get("status") == "ready"
        if bot_ok and user_ok:
            ok("飞书授权成功！")
            return True
        elif bot_ok and not user_ok:
            warn("仅 bot 身份就绪，user 身份缺失。部分功能（如 --sync）不可用")
            return True
        else:
            fail("授权后身份未就绪，请重试")
            return False
    else:
        fail("授权失败，请手动执行: lark-cli auth login")
        return False


# ══════════════════════════════════════════════════════
# 阶段 2：工具检查
# ══════════════════════════════════════════════════════

def check_node(quiet=False):
    """检查 node 是否可执行，返回路径"""
    # 优先 WorkBuddy managed
    base = Path.home() / ".workbuddy" / "binaries" / "node" / "versions"
    if base.exists():
        versions = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
        for v in versions:
            exe = v / "node.exe"
            if exe.exists():
                if not quiet:
                    rc, ver, _ = run_cmd(f'"{exe}" --version')
                    ok(f"Node.js 已安装 (managed): {ver.strip()}")
                return str(exe)

    # 系统 PATH
    rc, ver, _ = run_cmd("node --version")
    if rc == 0:
        if not quiet:
            ok(f"Node.js 已安装: {ver.strip()}")
        return "node"

    if not quiet:
        warn("Node.js 未安装，建议从 https://nodejs.org 下载安装")
    return None


def check_yt_dlp(quiet=False):
    """检查 yt-dlp 是否可执行"""
    rc, ver, _ = run_cmd("yt-dlp --version")
    if rc == 0:
        if not quiet:
            ok(f"yt-dlp 已安装: {ver.strip()}")
        return "yt-dlp"

    # 尝试 pip 安装的
    rc, out, _ = run_cmd("python -m yt_dlp --version")
    if rc == 0:
        if not quiet:
            ok(f"yt-dlp 已安装 (via pip): {out.strip()}")
        return "python -m yt_dlp"

    if not quiet:
        fail("yt-dlp 未安装")
    return None


def check_ffmpeg(quiet=False):
    """检查 ffmpeg 是否可用"""
    rc, ver, _ = run_cmd("ffmpeg -version")
    if rc == 0:
        ver_line = ver.splitlines()[0] if ver else ""
        if not quiet:
            ok(f"ffmpeg 已安装: {ver_line}")
        return "ffmpeg"

    # 尝试 imageio-ffmpeg
    rc, out, _ = run_cmd("python -c \"import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())\"")
    if rc == 0:
        if not quiet:
            ok(f"ffmpeg 已安装 (via imageio-ffmpeg): {out.strip()}")
        return out.strip()

    if not quiet:
        fail("ffmpeg 未安装")
    return None


def install_tool(name, pip_package=None, npm_package=None, extra_hint=None):
    """引导用户安装工具"""
    print()
    if pip_package:
        info(f"运行以下命令安装 {name}：")
        print(f"  pip install {pip_package}")
    if npm_package:
        info(f"运行以下命令安装 {name}：")
        print(f"  npm install -g {npm_package}")
    if extra_hint:
        info(extra_hint)

    if not input_yesno(f"  是否已安装完成 {name}？", default="n"):
        warn(f"请手动安装 {name} 后重试")


# ══════════════════════════════════════════════════════
# 阶段 3：feishu_config.json
# ══════════════════════════════════════════════════════

def check_feishu_config():
    """检查 feishu_config.json 状态"""
    config_file = SCRIPT_DIR / "feishu_config.json"

    if not config_file.exists():
        fail("feishu_config.json 不存在，尚未完成飞书配置")
        return None

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    chats = config.get("聊天列表", [])
    default_name = config.get("默认聊天名称", "")

    if not chats:
        fail("feishu_config.json 中无可用的聊天")
        return config

    # 检查是否有占位符 chat_id
    has_placeholder = any(
        c.get("chat_id", "").startswith("oc_xxxx") or
        c.get("chat_id", "") == "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
        for c in chats
    )
    if has_placeholder:
        warn("feishu_config.json 中存在占位符 chat_id，请运行 --sync 获取真实会话")

    # 检查默认聊天是否有效
    valid_default = any(c["名称"] == default_name for c in chats) if default_name else False
    if not valid_default and default_name:
        fail(f"默认聊天 \"{default_name}\" 在聊天列表中不存在")
    elif not valid_default:
        fail("未设置默认聊天")

    # 检查是否有真实 chat_id（非占位符）
    real_chats = [c for c in chats if not c.get("chat_id", "").startswith("oc_xxxx")]
    if real_chats:
        ok(f"已配置 {len(real_chats)} 个真实飞书会话")
        if valid_default:
            ok(f"默认聊天: {default_name}")
    else:
        fail("没有有效的真实聊天会话")

    return config


def sync_and_select_default():
    """运行 --sync 并交互选择默认聊天"""
    section("飞书聊天配置")

    info("正在同步飞书聊天列表...\n")
    rc, out, err = run_cmd(f'python "{SCRIPT_DIR / "feishu_send.py"}" --sync')
    print(out)
    if err:
        print(err)

    # 读取配置
    config_file = SCRIPT_DIR / "feishu_config.json"
    if not config_file.exists():
        fail("同步失败，feishu_config.json 未生成")
        return False

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    chats = config.get("聊天列表", [])
    if not chats:
        fail("同步后聊天列表为空")
        return False

    print(f"\n当前共 {len(chats)} 个聊天：\n")
    for i, chat in enumerate(chats, 1):
        cid = chat.get("chat_id", "")
        display_id = cid[:12] + "..." if len(cid) > 16 else cid
        print(f"  {i:2d}. {chat['名称']:35s} {display_id}")

    try:
        choice = input(f"\n请选择默认聊天 [1-{len(chats)}, Enter=跳过]: ").strip()
        if choice:
            idx = int(choice) - 1
            if 0 <= idx < len(chats):
                selected = chats[idx]
                config["默认聊天名称"] = selected["名称"]
                with open(config_file, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=4)
                ok(f"已设置默认聊天: {selected['名称']}")
                print()
            else:
                warn(f"无效选择: {choice}")
    except ValueError:
        warn("输入无效，已跳过")

    return True


# ══════════════════════════════════════════════════════
# 阶段 4：yt_config.json
# ══════════════════════════════════════════════════════

DEFAULT_YT_CONFIG = {
    "代理": {
        "启用": False,
        "协议": "socks5",
        "地址": "127.0.0.1",
        "端口": 10888
    },
    "认证": {
        "cookies文件": "youtube_cookies.txt"
    },
    "下载": {
        "输出目录": "downloads",
        "文件名模板": "%(title)s.%(ext)s",
        "格式选择": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best",
        "合并格式": "mp4",
        "最大高度": 1080,
        "限速": None,
        "同时下载片段数": 4
    },
    "工具路径": {
        "yt-dlp": "yt-dlp",
        "node": "",
        "ffmpeg": "ffmpeg"
    },
    "断点续传": {
        "启用": True,
        "临时文件后缀": ".part",
        "重试次数": 5,
        "重试间隔秒": 10
    },
    "信息文件": {
        "启用": True,
        "格式": "txt",
        "包含字段": [
            "标题", "URL", "时长", "上传者", "上传日期",
            "观看次数", "点赞数", "描述", "分辨率", "文件大小",
            "格式", "下载时间", "视频ID"
        ]
    },
    "字幕": {
        "启用": False,
        "语言": ["zh-Hans", "zh", "en"],
        "自动生成": True,
        "嵌入视频": True
    },
    "后处理": {
        "保留音频": False,
        "音频格式": "m4a",
        "webm转mp4": True,
        "转码文件前缀": "z_"
    }
}


def configure_yt_config():
    """检查并配置 yt_config.json"""
    section("YouTube 下载配置")

    config_file = SCRIPT_DIR / "yt_config.json"
    example_file = SCRIPT_DIR / "yt_config.example.json"

    # 优先读取现有配置，否则从 example 复制，否则用默认
    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                config = json.load(f)
            info("已存在 yt_config.json，将检测工具路径并补全配置")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            warn(f"yt_config.json 解析失败 ({e})，将重置为默认配置")
            config_file_backup = config_file.with_suffix(".json.bak")
            shutil.copy2(config_file, config_file_backup)
            info(f"已备份损坏文件至: {config_file_backup.name}")
            if example_file.exists():
                with open(example_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                info("从 yt_config.example.json 恢复配置")
            else:
                config = copy.deepcopy(DEFAULT_YT_CONFIG)
                info("使用默认配置模板")
            # 立即写入恢复后的配置，避免后续中断丢失
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            info("已写入恢复后的配置")
    elif example_file.exists():
        with open(example_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        info("从 yt_config.example.json 创建配置")
    else:
        config = DEFAULT_YT_CONFIG
        info("使用默认配置模板")

    # 收集工具路径
    yt_dlp_path = check_yt_dlp(quiet=True)
    node_path = check_node(quiet=True)
    ffmpeg_path = check_ffmpeg(quiet=True)

    tools_changed = False
    if "工具路径" not in config:
        config["工具路径"] = {}
        tools_changed = True

    if yt_dlp_path and config["工具路径"].get("yt-dlp") != yt_dlp_path:
        config["工具路径"]["yt-dlp"] = yt_dlp_path
        ok(f"检测到 yt-dlp: {yt_dlp_path}")
        tools_changed = True
    elif yt_dlp_path:
        ok(f"yt-dlp 路径已配置: {config['工具路径']['yt-dlp']}")
    else:
        warn("yt-dlp 未安装，配置中保持默认")

    if node_path and config["工具路径"].get("node") != node_path:
        config["工具路径"]["node"] = node_path
        ok(f"检测到 Node.js: {node_path}")
        tools_changed = True
    elif node_path:
        ok(f"Node.js 路径已配置: {config['工具路径']['node']}")
    else:
        warn("Node.js 未安装")

    if ffmpeg_path and config["工具路径"].get("ffmpeg") != ffmpeg_path:
        config["工具路径"]["ffmpeg"] = ffmpeg_path
        ok(f"检测到 ffmpeg: {ffmpeg_path}")
        tools_changed = True
    elif ffmpeg_path:
        ok(f"ffmpeg 路径已配置: {config['工具路径']['ffmpeg']}")
    else:
        warn("ffmpeg 未安装")

    # 代理配置
    print()
    if config.get("代理", {}).get("启用"):
        info("当前代理: 已启用")
        proxy = config["代理"]
        print(f"           协议: {proxy.get('协议', 'socks5')}")
        print(f"           地址: {proxy.get('地址', '127.0.0.1')}")
        print(f"           端口: {proxy.get('端口', 10888)}")
    else:
        info("当前代理: 未启用")

    if input_yesno("  是否需要配置代理？", default="n"):
        if "代理" not in config:
            config["代理"] = {}

        protocol = input_optional("  代理协议", default=config["代理"].get("协议", "socks5"))
        address = input_optional("  代理地址", default=config["代理"].get("地址", "127.0.0.1"))
        port_str = input_optional("  代理端口", default=str(config["代理"].get("端口", "10888")))

        try:
            port = int(port_str)
        except ValueError:
            warn(f"端口 '{port_str}' 无效，使用默认 10888")
            port = 10888

        config["代理"]["启用"] = True
        config["代理"]["协议"] = protocol
        config["代理"]["地址"] = address
        config["代理"]["端口"] = port
        tools_changed = True
        ok("代理配置已更新")
    else:
        config["代理"]["启用"] = False
        tools_changed = True

    # 保存
    if tools_changed or not config_file.exists():
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=4)
        ok(f"配置已保存: {config_file}")
    else:
        info("配置无需变更")

    return True


# ══════════════════════════════════════════════════════
# 阶段 5：汇总报告
# ══════════════════════════════════════════════════════

def summary_report(results):
    """打印检查结果汇总"""
    section("检查结果汇总")

    rows = [
        ("lark-cli 安装", "lark_installed"),
        ("lark-cli 授权", "lark_auth"),
        ("feishu_config.json", "feishu_ok"),
        ("默认聊天已设置", "default_chat"),
        ("yt-dlp 安装", "yt_dlp_ok"),
        ("Node.js 安装", "node_ok"),
        ("ffmpeg 安装", "ffmpeg_ok"),
        ("yt_config.json", "yt_config_ok"),
    ]

    for label, key in rows:
        status = results.get(key)
        if status is True:
            ok(label)
        elif status is False:
            fail(label)
        else:
            warn(f"{label} (未检查)")

    print()
    all_pass = all(v is True for v in results.values())
    if all_pass:
        info(f"所有检查通过！现在可以运行 python task_engine.py 启动引擎了。")
    else:
        issues = sum(1 for v in results.values() if v is False)
        info(f"共 {issues} 个检查项未通过，请根据上方提示修复后重试。")
    print()


# ══════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════

def main():
    print()
    print(f"{BOLD}+---- 飞书任务引擎 - 环境检查与配置引导 ----+{RESET}")
    print()

    results = {}

    # ─── Stage 1: lark-cli 安装 ────────────────────
    section("1. lark-cli 检查")
    lark_path = check_lark_cli()
    if lark_path:
        ok(f"lark-cli 已找到: {lark_path}")
        results["lark_installed"] = True
    else:
        fail("lark-cli 未安装")
        results["lark_installed"] = False
        info("安装方式: npm install -g @larksuite/cli")
        info("或通过 WorkBuddy 飞书连接器自动管理")

    # ─── Stage 2: lark-cli 授权 ────────────────────
    if results["lark_installed"]:
        auth_data = check_lark_auth()
        if auth_data and auth_data.get("verified"):
            identities = auth_data.get("identities", {})
            bot_status = identities.get("bot", {}).get("status", "")
            user_status = identities.get("user", {}).get("status", "")

            # 必须 bot 和 user 身份都 ready 才算完整授权
            all_ready = (bot_status == "ready") and (user_status == "ready")

            if all_ready:
                ok("lark-cli 已完整授权登录")
                results["lark_auth"] = True
                for role in ["bot", "user"]:
                    info(f"  {role} 身份: ready")
            else:
                warn("lark-cli 授权不完整")
                for role in ["bot", "user"]:
                    id_info = identities.get(role, {})
                    status = id_info.get("status", "missing")
                    msg = id_info.get("message", "")
                    info(f"  {role} 身份: {status}" + (f" ({msg})" if msg else ""))
                results["lark_auth"] = False
                if input_yesno("  是否现在完成完整授权（需扫码登录飞书）？", default="y"):
                    if run_lark_login():
                        results["lark_auth"] = True
                else:
                    fail("授权失败")
        else:
            results["lark_auth"] = False
            warn("lark-cli 未授权")
            if input_yesno("  是否现在登录授权？"):
                if run_lark_login():
                    results["lark_auth"] = True
                else:
                    fail("授权失败")

    # 授权不充分 → 直接中断，不再继续后续检查
    if not results.get("lark_auth"):
        fail("飞书授权未完成，环境检查终止。请先完成授权后重试")
        summary_report(results)
        return

    # ─── Stage 3: feishu_config.json ───────────────
    section("2. feishu_config.json 检查")

    # ─── Stage 3: feishu_config.json ───────────────
    section("2. feishu_config.json 检查")
    feishu_config = check_feishu_config()
    results["feishu_ok"] = feishu_config is not None

    if feishu_config:
        default_name = feishu_config.get("默认聊天名称", "")
        has_valid = any(
            c["名称"] == default_name and not c.get("chat_id", "").startswith("oc_xxxx")
            for c in feishu_config.get("聊天列表", [])
        )
        results["default_chat"] = has_valid
    else:
        results["default_chat"] = False

    # 如果 feishu_config 有缺陷，引导同步
    if not results.get("feishu_ok"):
        if input_yesno("  是否同步飞书聊天列表并设置默认聊天？", default="y"):
            if sync_and_select_default():
                results["feishu_ok"] = True
                results["default_chat"] = True
    elif not results.get("default_chat"):
        if input_yesno("  默认聊天未设置，是否现在选择？", default="y"):
            sync_and_select_default()
            config = check_feishu_config()
            if config and config.get("默认聊天名称", ""):
                results["default_chat"] = True

    # ─── Stage 4: 工具依赖 ─────────────────────────
    section("3. 工具依赖检查")

    yt_dlp = check_yt_dlp()
    results["yt_dlp_ok"] = yt_dlp is not None
    if not yt_dlp:
        install_tool("yt-dlp", pip_package="yt-dlp")

    node = check_node()
    results["node_ok"] = node is not None
    if not node:
        install_tool("Node.js", extra_hint="从 https://nodejs.org 下载安装")

    ffmpeg = check_ffmpeg()
    results["ffmpeg_ok"] = ffmpeg is not None
    if not ffmpeg:
        install_tool("ffmpeg", pip_package="imageio-ffmpeg")

    # ─── Stage 5: yt_config.json ───────────────────
    results["yt_config_ok"] = configure_yt_config()

    # ─── 汇总 ──────────────────────────────────────
    summary_report(results)


if __name__ == "__main__":
    main()

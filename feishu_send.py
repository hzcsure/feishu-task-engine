"""
飞书CLI 交互式聊天脚本（专用于飞书CLI机器人聊天）
用法:
  python feishu_send.py                    # 直接进入聊天模式
  python feishu_send.py "你好"             # 发送单条消息
  python feishu_send.py -m "## 标题"       # 发送 markdown
  python feishu_send.py --image photo.png  # 发送图片
  python feishu_send.py --file doc.pdf     # 发送文件
  python feishu_send.py --list             # 列出所有聊天
  python feishu_send.py --sync             # 同步聊天列表
"""
import os
import re
import sys
import json
import time
import argparse
import subprocess
import threading
from pathlib import Path
from queue import Queue, Empty

# Windows 终端编码兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "feishu_config.json"


# ================================
# Node / lark-cli 查找
# ================================
def find_node_exe():
    """查找 managed node.exe 路径"""
    result = subprocess.run(["where", "node"], capture_output=True, shell=True)
    if result.returncode == 0 and result.stdout.strip():
        text = result.stdout.decode("utf-8", errors="replace").strip()
        return text.splitlines()[0]
    base = Path.home() / ".workbuddy" / "binaries" / "node" / "versions"
    if base.exists():
        versions = sorted([d for d in base.iterdir() if d.is_dir()], reverse=True)
        for v in versions:
            exe = v / "node.exe"
            if exe.exists():
                return str(exe)
    return None


def find_lark_cli():
    """自动查找 lark-cli 可执行文件路径"""
    for name in ["lark-cli.cmd", "lark-cli.exe", "lark-cli"]:
        result = subprocess.run(["where", name], capture_output=True, shell=True)
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout.decode("utf-8", errors="replace").strip()
            path = text.splitlines()[0]
            if path.endswith((".cmd", ".exe", ".bat")):
                return path
    base = Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages"
    for ext in [".cmd", ".exe", ".bat", ""]:
        candidate = base / f"lark-cli{ext}"
        if candidate.exists() and ext:
            return str(candidate)
    return "lark-cli"


def find_lark_run_js():
    """查找 lark-cli 的 run.js 脚本路径"""
    base = Path.home() / ".workbuddy" / "binaries" / "node" / "cli-connector-packages"
    run_js = base / "node_modules" / "@larksuite" / "cli" / "scripts" / "run.js"
    if run_js.exists():
        return str(run_js)
    return None


LARK_CLI = None
NODE_EXE = None
LARK_RUN_JS = None


def get_lark_cli():
    global LARK_CLI
    if LARK_CLI is None:
        LARK_CLI = find_lark_cli()
    return LARK_CLI


def get_node_exe():
    global NODE_EXE
    if NODE_EXE is None:
        NODE_EXE = find_node_exe()
    return NODE_EXE


def get_lark_run_js():
    global LARK_RUN_JS
    if LARK_RUN_JS is None:
        LARK_RUN_JS = find_lark_run_js()
    return LARK_RUN_JS


DEFAULT_CONFIG = {
    "默认聊天名称": "",
    "默认身份": "bot",
    "聊天列表": [
        {
            "名称": "飞书CLI",
            "chat_id": "oc_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "备注": "与飞书CLI机器人的单聊"
        }
    ]
}


# ================================
# 配置管理
# ================================
def load_config():
    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        print(f"已创建默认配置文件: {CONFIG_FILE}")
        return DEFAULT_CONFIG
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)


def find_chat_by_name(config, name):
    for chat in config.get("聊天列表", []):
        if chat["名称"] == name:
            return chat
    matches = [c for c in config.get("聊天列表", []) if name.lower() in c["名称"].lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"找到多个匹配的聊天:")
        for i, m in enumerate(matches):
            print(f"  {i+1}. {m['名称']} -> {m['chat_id']}")
        choice = input("选择编号 (回车取消): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            return matches[int(choice) - 1]
    return None


def resolve_chat_id(config, args):
    """确定聊天目标，优先用配置中的默认聊天"""
    if args.chat_id:
        for chat in config.get("聊天列表", []):
            if chat["chat_id"] == args.chat_id:
                return args.chat_id, chat["名称"]
        return args.chat_id, "(未命名)"
    if args.to:
        chat = find_chat_by_name(config, args.to)
        if chat:
            return chat["chat_id"], chat["名称"]
        print(f"错误: 未找到名为 '{args.to}' 的聊天")
        sys.exit(1)
    # 使用配置中的默认聊天
    default_name = config.get("默认聊天名称", "")
    if default_name:
        chat = find_chat_by_name(config, default_name)
        if chat:
            return chat["chat_id"], chat["名称"]
    # 兜底：取聊天列表第一个
    chats = config.get("聊天列表", [])
    if chats:
        return chats[0]["chat_id"], chats[0]["名称"]
    print("错误: 配置中没有聊天目标，请先运行 --sync 同步聊天列表")
    sys.exit(1)


# ================================
# 飞书 CLI 调用
# ================================
def run_lark_cli(args_list, timeout=30):
    """执行 lark-cli 命令，返回 (成功, JSON结果)"""
    node_exe = get_node_exe()
    run_js = get_lark_run_js()

    if node_exe and run_js:
        cmd = [node_exe, run_js] + args_list
        env = os.environ.copy()
        node_dir = str(Path(node_exe).parent)
        env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
    else:
        cmd = [get_lark_cli()] + args_list
        env = os.environ.copy()
        if node_exe:
            node_dir = str(Path(node_exe).parent)
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")

    try:
        # 用 bytes 读取再手动 UTF-8 解码，避免 Windows 编码问题
        result = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env)
        stdout_text = result.stdout.decode("utf-8", errors="replace")
        stderr_text = result.stderr.decode("utf-8", errors="replace")

        if result.returncode == 0:
            try:
                data = json.loads(stdout_text.strip())
                return True, data
            except json.JSONDecodeError:
                return True, {"raw": stdout_text.strip()}
        else:
            return False, {"error": (stderr_text or stdout_text or "").strip()}
    except FileNotFoundError:
        return False, {"error": f"未找到 node.exe 或 lark-cli: node={node_exe}, lark_cli={get_lark_cli()}"}
    except subprocess.TimeoutExpired:
        return False, {"error": "lark-cli 执行超时"}
    except Exception as e:
        return False, {"error": str(e)}


def send_text(chat_id, text, identity="bot"):
    return run_lark_cli(["im", "+messages-send",
                         "--chat-id", chat_id,
                         "--text", text,
                         "--as", identity,
                         "--json"])


def send_markdown(chat_id, markdown, identity="bot"):
    post_content = markdown_to_post(markdown)
    content_json = json.dumps(post_content, ensure_ascii=False)
    return run_lark_cli(["im", "+messages-send",
                         "--chat-id", chat_id,
                         "--msg-type", "post",
                         "--content", content_json,
                         "--as", identity,
                         "--json"])


def send_image(chat_id, image_path, identity="bot"):
    if not Path(image_path).exists():
        return False, {"error": f"图片文件不存在: {image_path}"}
    return run_lark_cli(["im", "+messages-send",
                         "--chat-id", chat_id,
                         "--image", image_path,
                         "--as", identity,
                         "--json"])


def send_file(chat_id, file_path, identity="bot"):
    if not Path(file_path).exists():
        return False, {"error": f"文件不存在: {file_path}"}
    return run_lark_cli(["im", "+messages-send",
                         "--chat-id", chat_id,
                         "--file", file_path,
                         "--as", identity,
                         "--json"])


def list_chats():
    return run_lark_cli(["im", "+chat-list", "--types", "p2p,group", "--json"])


def sync_chats_to_config(config):
    ok, data = list_chats()
    if not ok:
        print(f"获取聊天列表失败: {data.get('error')}")
        return
    chats = data.get("data", {}).get("chats", [])
    if not chats:
        print("未获取到任何聊天")
        return
    existing_ids = {c["chat_id"] for c in config.get("聊天列表", [])}
    added = 0
    for chat in chats:
        chat_id = chat.get("chat_id", "")
        if chat_id in existing_ids:
            continue
        chat_mode = chat.get("chat_mode", "")
        name = chat.get("name", "")
        if not name:
            name = f"聊天_{chat_id[-8:]}"
        config.setdefault("聊天列表", []).append({
            "名称": name,
            "chat_id": chat_id,
            "备注": f"{chat_mode}"
        })
        existing_ids.add(chat_id)
        added += 1
    save_config(config)
    print(f"同步完成: 新增 {added} 个聊天，共 {len(config['聊天列表'])} 个")


# ================================
# 消息接收 / 解析
# ================================
def list_messages(chat_id, identity="bot", page_size=20, start_time=None, end_time=None, order="desc"):
    """获取聊天消息列表"""
    args = ["im", "+chat-messages-list",
            "--chat-id", chat_id,
            "--as", identity,
            "--page-size", str(page_size),
            "--order", order,
            "--json"]
    if start_time:
        args.extend(["--start", start_time])
    if end_time:
        args.extend(["--end", end_time])
    return run_lark_cli(args, timeout=20)


def extract_display_text(msg):
    """从消息对象提取可显示的纯文本"""
    msg_type = msg.get("msg_type", "")
    content = msg.get("content", "")

    if msg_type == "text":
        return content

    if msg_type == "post":
        # 尝试解析飞书 post 格式 (JSON)
        try:
            post_data = json.loads(content)
            lines = []
            title = post_data.get("zh_cn", {}).get("title", "")
            if title:
                lines.append(f"【{title}】")
            for line in post_data.get("zh_cn", {}).get("content", []):
                line_texts = []
                for elem in line:
                    text_val = elem.get("text", "")
                    styles = elem.get("style", [])
                    if "bold" in styles:
                        text_val = f"*{text_val}*"
                    line_texts.append(text_val)
                lines.append(" ".join(line_texts))
            return "\n".join(lines)
        except (json.JSONDecodeError, KeyError, TypeError):
            # content 可能已经是格式化文本
            return content

    if msg_type == "image":
        return "[图片]"

    if msg_type == "file":
        # 尝试解析文件名
        try:
            file_data = json.loads(content)
            fname = file_data.get("file_name", file_data.get("name", ""))
            return f"[文件: {fname}]" if fname else "[文件]"
        except:
            return "[文件]"

    if msg_type == "audio":
        return "[音频]"

    if msg_type == "video":
        return "[视频]"

    if msg_type == "sticker":
        return "[表情]"

    # 其他类型
    return content if len(content) < 100 else content[:100] + "..."


def format_sender_label(msg, my_sender_id=None):
    """格式化发送者标签"""
    sender = msg.get("sender", {})
    sender_type = sender.get("sender_type", "")
    sender_id = sender.get("id", "")

    # 判断是否是自己发的
    if my_sender_id and sender_id == my_sender_id:
        return "我"

    if sender_type == "app":
        return "BOT"
    elif sender_type == "user":
        # 尝试取 sender_name (lark-cli 有时会自动 enrich)
        name = sender.get("sender_name", sender.get("name", ""))
        if name:
            return name
        return f"User({sender_id[:8]})"

    return sender_type


# ================================
# Markdown → 飞书 post 转换
# ================================
def markdown_to_post(md_text):
    lines = md_text.strip().split("\n")
    title = ""
    content = []
    for line in lines:
        line = line.rstrip()
        if not line:
            continue
        m = re.match(r"^#{1,3}\s+(.+)", line)
        if m and not title:
            title = m.group(1).strip()
            continue
        m = re.match(r"^[-*]\s+(.+)", line)
        if m:
            text = m.group(1)
            elems = parse_inline(text, prefix="- ")
            content.append(elems if isinstance(elems, list) else [elems])
            continue
        elems = parse_inline(line)
        content.append(elems if isinstance(elems, list) else [elems])
    post = {"zh_cn": {"content": content}}
    if title:
        post["zh_cn"]["title"] = title
    return post


def parse_inline(text, prefix=""):
    if "**" not in text and "*" not in text:
        return {"tag": "text", "text": prefix + text}
    elements = []
    remaining = prefix + text
    pattern = re.compile(r"(\*\*(.+?)\*\*|\*(.+?)\*)")
    last_end = 0
    for m in pattern.finditer(remaining):
        if m.start() > last_end:
            elements.append({"tag": "text", "text": remaining[last_end:m.start()]})
        if m.group(2):
            elements.append({"tag": "text", "text": m.group(2), "style": ["bold"]})
        elif m.group(3):
            elements.append({"tag": "text", "text": m.group(3), "style": ["italic"]})
        last_end = m.end()
    if last_end < len(remaining):
        elements.append({"tag": "text", "text": remaining[last_end:]})
    if len(elements) == 1:
        return elements[0]
    return elements


# ================================
# 交互式选择聊天
# ================================
def interactive_select(config):
    chats = config.get("聊天列表", [])
    if not chats:
        print("聊天列表为空，正在同步...")
        sync_chats_to_config(config)
        config = load_config()
        chats = config.get("聊天列表", [])
    print("\n可用聊天:")
    for i, chat in enumerate(chats):
        default_mark = " (默认)" if chat["名称"] == config.get("默认聊天名称") else ""
        print(f"  {i+1}. {chat['名称']}{default_mark}  [{chat['chat_id']}]")
        if chat.get("备注"):
            print(f"     备注: {chat['备注']}")
    choice = input(f"\n选择编号 (1-{len(chats)}, 回车使用默认): ").strip()
    if not choice:
        default_name = config.get("默认聊天名称", "")
        if default_name:
            chat = find_chat_by_name(config, default_name)
            if chat:
                return chat["chat_id"], chat["名称"]
        print("未设置默认聊天，请选择编号")
        sys.exit(1)
    if choice.isdigit() and 1 <= int(choice) <= len(chats):
        chat = chats[int(choice) - 1]
        return chat["chat_id"], chat["名称"]
    print("无效选择")
    sys.exit(1)


# ================================
# 交互式聊天模式
# ================================
EXIT_KEYWORDS = ["结束会话", "结束对话", "end session", "/end"]


def check_exit_keyword(display_text, sender_label):
    """检测退出关键词，仅对方发送时生效（自己发的不触发）"""
    if sender_label == "我":
        return False
    text = display_text.strip()
    for kw in EXIT_KEYWORDS:
        if kw == text or kw in text:
            return True
    return False


def chat_mode(chat_id, chat_name, identity="bot"):
    """
    交互式聊天模式:
    - 后台线程轮询消息，新消息自动显示
    - 用户输入 → 发送
    - 检测到 "结束会话" → 退出
    """
    print("=" * 50)
    print(f"  飞书交互式聊天")
    print(f"  聊天: {chat_name}  [{chat_id}]")
    print(f"  身份: {identity}")
    print(f"  命令: /quit 退出, /refresh 刷新消息, /help 查看帮助")
    print("=" * 50)

    # 获取自己的 sender_id
    my_sender_id = None
    if identity == "bot":
        # bot 的 sender_id 就是 app_id，从 lark-cli 获取
        # 暂时用发送一条消息后的返回值来获取
        # 先用占位：从最新消息中推断
        pass

    # 加载历史消息，记录最后消息位置
    last_msg_time = None
    known_msg_ids = set()

    # 先显示最近的消息
    print("\n--- 最近消息 ---")
    ok, data = list_messages(chat_id, identity, page_size=10, order="desc")
    if ok:
        messages = data.get("data", {}).get("messages", [])
        # 按时间正序显示
        messages.sort(key=lambda m: m.get("create_time", ""))
        for msg in messages:
            msg_id = msg.get("message_id", "")
            known_msg_ids.add(msg_id)
            display_text = extract_display_text(msg)
            sender_label = format_sender_label(msg, my_sender_id)
            create_time = msg.get("create_time", "")
            print(f"  [{create_time}] {sender_label}: {display_text}")
        if messages:
            last_msg_time = messages[-1].get("create_time", "")
    else:
        print(f"  获取消息失败: {data.get('error', '未知错误')}")

    print("--- 消息结束 ---\n")

    # 线程间通信
    msg_queue = Queue()      # 新消息队列
    input_queue = Queue()    # 用户输入队列
    exit_event = threading.Event()  # 退出信号

    # 消息轮询线程
    def poll_messages():
        poll_interval = 3  # 秒
        while not exit_event.is_set():
            try:
                # 不用 start_time 过滤，每次拉最新 N 条，靠 known_msg_ids 去重
                ok, data = list_messages(chat_id, identity, page_size=10, order="desc")
                if ok:
                    messages = data.get("data", {}).get("messages", [])
                    new_msgs = []
                    for msg in messages:
                        msg_id = msg.get("message_id", "")
                        if msg_id not in known_msg_ids:
                            known_msg_ids.add(msg_id)
                            new_msgs.append(msg)
                    if new_msgs:
                        # 按时间正序
                        new_msgs.sort(key=lambda m: m.get("create_time", ""))
                        for msg in new_msgs:
                            msg_queue.put(msg)
                            # 更新最后消息时间
                            ct = msg.get("create_time", "")
                            if ct:
                                last_msg_time = ct
                else:
                    # 轮询失败，静默忽略
                    pass
            except Exception:
                pass
            exit_event.wait(poll_interval)

    # 用户输入线程
    def input_loop():
        while not exit_event.is_set():
            try:
                line = input()
                input_queue.put(line)
            except (EOFError, KeyboardInterrupt):
                input_queue.put("/quit")
                break

    # 启动线程
    poll_thread = threading.Thread(target=poll_messages, daemon=True)
    input_thread = threading.Thread(target=input_loop, daemon=True)
    poll_thread.start()
    input_thread.start()

    # 主循环：协调显示和逻辑
    prompt_state = {"shown": False}  # 用 dict 避免 nonlocal 闭包问题

    def show_prompt():
        if not prompt_state["shown"]:
            print(f"\r> ", end="", flush=True)
            prompt_state["shown"] = True

    def clear_prompt():
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()
        prompt_state["shown"] = False

    show_prompt()

    while not exit_event.is_set():
        # 1. 检查新消息
        new_messages = []
        while not msg_queue.empty():
            try:
                msg = msg_queue.get_nowait()
                new_messages.append(msg)
            except Empty:
                break

        if new_messages:
            clear_prompt()
            for msg in new_messages:
                display_text = extract_display_text(msg)
                sender_label = format_sender_label(msg, my_sender_id)
                create_time = msg.get("create_time", "")
                print(f"  [{create_time}] {sender_label}: {display_text}")

                # 检测 "结束会话"（仅对方发送时生效）
                if check_exit_keyword(display_text, sender_label):
                    print(f"\n  *** 对方发送了「{display_text.strip()}」，聊天结束 ***")
                    exit_event.set()
                    break

            if not exit_event.is_set():
                show_prompt()

        # 2. 检查用户输入
        try:
            line = input_queue.get(timeout=0.5)
        except Empty:
            continue

        prompt_shown = False

        if not line.strip():
            # 空行 → 刷新提示
            show_prompt()
            continue

        # 处理命令
        cmd = line.strip().lower()

        if cmd in ("/quit", "/exit", "/q"):
            print("  退出聊天模式")
            exit_event.set()
            break

        if cmd == "/refresh":
            # 强制刷新消息并显示
            ok, data = list_messages(chat_id, identity, page_size=20, order="desc")
            if ok:
                messages = data.get("data", {}).get("messages", [])
                new_msgs = []
                for msg in messages:
                    msg_id = msg.get("message_id", "")
                    if msg_id not in known_msg_ids:
                        known_msg_ids.add(msg_id)
                        new_msgs.append(msg)
                if new_msgs:
                    new_msgs.sort(key=lambda m: m.get("create_time", ""))
                    clear_prompt()
                    print(f"  刷新完成: {len(new_msgs)} 条新消息:")
                    for msg in new_msgs:
                        display_text = extract_display_text(msg)
                        sender_label = format_sender_label(msg, my_sender_id)
                        create_time = msg.get("create_time", "")
                        print(f"    [{create_time}] {sender_label}: {display_text}")
                        ct = msg.get("create_time", "")
                        if ct:
                            last_msg_time = ct
                        # 检测退出关键词
                        if check_exit_keyword(display_text, sender_label):
                            print(f"\n  *** 对方发送了「{display_text.strip()}」，聊天结束 ***")
                            exit_event.set()
                            break
                    if not exit_event.is_set():
                        show_prompt()
                else:
                    print("  没有新消息")
                    show_prompt()
            continue

        if cmd == "/help":
            print("  命令列表:")
            print("    /quit, /exit, /q  - 退出聊天模式")
            print("    /refresh          - 强制刷新消息")
            print("    /help             - 查看帮助")
            print("    其他文本          - 发送消息")
            print("  退出条件:")
            print("    对方发送「结束会话」自动退出")
            show_prompt()
            continue

        # 发送消息
        ok, result = send_text(chat_id, line.strip(), identity)
        if ok:
            data = result.get("data", result)
            msg_id = data.get("message_id", "")
            # 获取自己的 sender_id
            if not my_sender_id and identity == "bot":
                # 从消息的 sender 信息获取 app_id
                # 消息返回可能不包含 sender 详情，需要单独查
                pass
            print(f"  [已发送] {msg_id}")
        else:
            print(f"  [发送失败] {result.get('error', '未知错误')}")

        show_prompt()

    exit_event.set()
    print("\n聊天模式结束。")


# ================================
# 主流程
# ================================
def main():
    parser = argparse.ArgumentParser(
        description="飞书CLI 交互式聊天工具（默认进入聊天模式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
快速使用:
  python feishu_send.py                # 直接进入聊天模式（默认：飞书CLI）
  python feishu_send.py "你好"         # 发送单条消息
  python feishu_send.py --list         # 列出所有飞书聊天
""")
    parser.add_argument("text", nargs="?", help="要发送的文本内容（无参数则进入聊天模式）")
    parser.add_argument("-m", "--markdown", help="发送 markdown 格式消息")
    parser.add_argument("--image", help="发送图片 (本地文件路径)")
    parser.add_argument("--file", help="发送文件 (本地文件路径)")
    parser.add_argument("--to", help="临时指定聊天目标（覆盖默认）")
    parser.add_argument("--chat-id", help="临时指定 chat_id（覆盖默认）")
    parser.add_argument("--as", dest="identity_type", choices=["bot", "user"], help="发送身份 (默认bot)")
    parser.add_argument("--list", action="store_true", help="列出所有飞书聊天")
    parser.add_argument("--sync", action="store_true", help="从飞书同步聊天列表到配置文件")
    parser.add_argument("--chat", action="store_true", help="显式进入聊天模式（默认行为）")
    parser.add_argument("--set-default", help="设置默认聊天名称")
    args = parser.parse_args()

    config = load_config()

    # --- 管理命令 ---
    if args.list:
        ok, data = list_chats()
        if ok:
            chats = data.get("data", {}).get("chats", [])
            print(f"\n飞书聊天列表 ({len(chats)} 个):\n")
            for chat in chats:
                chat_mode_val = chat.get("chat_mode", "")
                name = chat.get("name", "(无名称)")
                chat_id = chat.get("chat_id", "")
                status = chat.get("chat_status", "")
                print(f"  [{chat_mode_val:5s}] {name:25s} {chat_id}  ({status})")
        else:
            print(f"获取失败: {data.get('error')}")
        return

    if args.sync:
        sync_chats_to_config(config)
        return

    if args.set_default:
        chat = find_chat_by_name(config, args.set_default)
        if chat:
            config["默认聊天名称"] = args.set_default
            save_config(config)
            print(f"已设置默认聊天: {args.set_default}")
        else:
            print(f"未找到聊天: {args.set_default}")
        return

    # --- 确定聊天目标（始终使用默认聊天） ---
    chat_id, chat_name = resolve_chat_id(config, args)

    identity = args.identity_type or config.get("默认身份", "bot")

    # --- 无参数或 --chat → 进入聊天模式 ---
    no_send_content = not (args.text or args.markdown or args.image or args.file)
    if args.chat or no_send_content:
        chat_mode(chat_id, chat_name, identity)
        return

    # --- 单次发送消息 ---
    if args.image:
        print(f"发送图片到 [{chat_name}] ...")
        ok, result = send_image(chat_id, args.image, identity)
    elif args.file:
        print(f"发送文件到 [{chat_name}] ...")
        ok, result = send_file(chat_id, args.file, identity)
    elif args.markdown:
        print(f"发送 markdown 消息到 [{chat_name}] ...")
        ok, result = send_markdown(chat_id, args.markdown, identity)
    elif args.text:
        print(f"发送文本到 [{chat_name}] ...")
        ok, result = send_text(chat_id, args.text, identity)
    else:
        print("错误: 请提供消息内容 (文本/markdown/图片/文件) 或使用 --chat 进入聊天模式")
        parser.print_help()
        sys.exit(1)

    if ok:
        data = result.get("data", result)
        msg_id = data.get("message_id", "")
        print(f"[OK] 发送成功! 消息ID: {msg_id}")
    else:
        error = result.get("error", "未知错误")
        print(f"[FAIL] 发送失败: {error}")


if __name__ == "__main__":
    main()

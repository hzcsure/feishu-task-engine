"""
task_engine.py - 飞书任务调度引擎

通过飞书消息接收任务登记请求，发送表单收集要素，
登记并调度本地任务执行（如YouTube下载），支持状态查询。

依赖:
  - feishu_send.py (消息收发)
  - task_configs.json (任务类型定义)
  - tasks.json (任务持久化存储)

用法:
  python task_engine.py                    # 启动引擎（前台运行）
  python task_engine.py --daemon           # 后台运行模式
"""
import os
import re
import sys
import json
import time
import copy
import threading
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from queue import Queue, Empty

# Windows 终端编码兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).parent

# 引入 feishu_send 的飞书通信能力
sys.path.insert(0, str(SCRIPT_DIR))
import feishu_send as fs

# ============ 文件路径 ============
TASK_CONFIG_FILE = SCRIPT_DIR / "task_configs.json"
TASKS_FILE = SCRIPT_DIR / "tasks.json"


# ================================
# 配置加载
# ================================
def load_task_configs():
    """加载任务类型配置"""
    if not TASK_CONFIG_FILE.exists():
        print(f"错误: 任务配置文件不存在: {TASK_CONFIG_FILE}")
        sys.exit(1)
    with open(TASK_CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("任务类型", [])


def find_task_type(task_types, task_ident):
    """按标识或名称查找任务类型"""
    for tt in task_types:
        if tt.get("标识") == task_ident or tt.get("名称") == task_ident:
            return tt
    # 模糊匹配
    for tt in task_types:
        if task_ident.lower() in tt.get("标识", "").lower() or \
           task_ident.lower() in tt.get("名称", "").lower():
            return tt
    return None


# ================================
# 任务持久化
# ================================
def load_tasks():
    """从 tasks.json 加载任务数据"""
    if not TASKS_FILE.exists():
        return {"tasks": {}, "counter": 0, "counter_date": ""}
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tasks(data):
    """写入 tasks.json"""
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def generate_task_id(data):
    """生成任务ID: T-YYYYMMDD-NNN"""
    today = datetime.now().strftime("%Y-%m-%d")
    if data.get("counter_date") != today:
        data["counter"] = 0
        data["counter_date"] = today
    data["counter"] += 1
    date_str = today.replace("-", "")
    task_id = f"T-{date_str}-{data['counter']:03d}"
    return task_id


def build_exec_plan(stage_list, fields, task_id=""):
    """从配置映射的「阶段列表」构建执行计划"""
    exec_plan = []
    for stage in stage_list:
        cmd_template = stage.get("命令行", [])
        rendered_cmd = []
        for part in cmd_template:
            if part.startswith("{") and part.endswith("}"):
                expr = part[1:-1]
                # 支持 {fields.xxx} 语法
                if expr.startswith("fields."):
                    rendered_cmd.append(fields.get(expr[7:], ""))
                elif expr == "task_id":
                    rendered_cmd.append(task_id)
                else:
                    rendered_cmd.append(fields.get(expr, ""))
            else:
                rendered_cmd.append(part)
        exec_plan.append({
            "阶段名": stage.get("阶段名", "未知阶段"),
            "命令行": rendered_cmd,
            "失败策略": stage.get("失败策略", "中止"),
            "超时秒": stage.get("超时秒", 3600),
            "后处理适配器": stage.get("后处理适配器", ""),
            "输入准备适配器": stage.get("输入准备适配器", ""),
        })
    return exec_plan


def create_task(task_type, fields, chat_id, sender_label):
    """创建新任务记录（支持单阶段和多阶段）"""
    data = load_tasks()
    task_id = generate_task_id(data)

    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # 解析执行时间
    execute_at = fields.get("execute_time", "").strip()
    if not execute_at or execute_at == "立即":
        execute_at = now  # 立即执行

    # 从配置映射构建执行计划
    mapping = task_type.get("配置映射", {})
    stage_list = mapping.get("阶段列表", None)

    if stage_list:
        exec_plan = build_exec_plan(stage_list, fields, task_id)
    else:
        # 单阶段 → 包装为 1 个阶段的 exec_plan
        cmd = build_exec_cmd(mapping, fields)
        exec_plan = [{
            "阶段名": task_type.get("名称", "执行"),
            "命令行": cmd,
            "失败策略": "中止",
            "超时秒": 3600,
        }]

    task = {
        "type": task_type.get("标识", "unknown"),
        "type_name": task_type.get("名称", "未知"),
        "type_config": task_type.get("类型配置", {}),
        "status": "pending",
        "fields": fields,
        "exec_plan": exec_plan,
        "stage_results": {
            s["阶段名"]: {"status": "pending", "started_at": None, "finished_at": None, "error": None}
            for s in exec_plan
        },
        "execute_at": execute_at,
        "created_at": now,
        "started_at": None,
        "finished_at": None,
        "result": None,
        "error": None,
        "chat_id": chat_id,
        "created_by": sender_label,
    }
    data["tasks"][task_id] = task
    save_tasks(data)
    return task_id, task


def update_task_status(task_id, status, **extra):
    """更新任务状态"""
    data = load_tasks()
    if task_id not in data["tasks"]:
        return False
    task = data["tasks"][task_id]
    task["status"] = status
    for k, v in extra.items():
        task[k] = v
    save_tasks(data)
    return True


def delete_task(task_id):
    """从存储中彻底删除任务"""
    data = load_tasks()
    if task_id not in data["tasks"]:
        return False
    del data["tasks"][task_id]
    save_tasks(data)
    return True


def delete_all_tasks():
    """清空所有任务"""
    data = load_tasks()
    count = len(data["tasks"])
    data["tasks"] = {}
    save_tasks(data)
    return count


def build_exec_cmd(mapping, fields):
    """根据配置映射和表单字段构建执行命令"""
    cmd_template = mapping.get("命令行", [])
    cmd = []
    for part in cmd_template:
        # 替换 {字段名} 占位符
        if part.startswith("{") and part.endswith("}"):
            field_name = part[1:-1]
            cmd.append(fields.get(field_name, ""))
        else:
            cmd.append(part)
    return cmd


# ================================
# 表单生成与解析
# ================================
def build_form_text(task_type):
    """构建任务表单文本（发送给用户填写）"""
    name = task_type.get("名称", "未知")
    fields = task_type.get("要素列表", [])

    lines = [f"=== 登记任务：{name} ==="]
    lines.append(f"请逐行回复以下信息（每行一个字段，字段名: 值 格式）：")
    lines.append("")

    for f in fields:
        required = "必填" if f.get("必填") else "可选"
        default = f.get("默认", "")
        hint = f.get("提示", "")
        req_flag = "*" if f.get("必填") else " "
        line = f"  {req_flag}{f['显示名']} ({required})"
        if default:
            line += f" [默认: {default}]"
        if hint:
            line += f"\n    提示: {hint}"
        lines.append(line)

    lines.append("")
    lines.append("示例回复:")
    lines.append("""
视频链接: https://youtu.be/xxx
标题: 我的视频
描述: 好视频
内容标签: AI, 教程
执行时间: 2026-06-26 20:00
""".strip())
    return "\n".join(lines)


def parse_form_reply(reply_text, task_type):
    """解析用户对表单的回复，返回 {字段名: 值} 字典"""
    fields = task_type.get("要素列表", [])
    result = {}

    lines = [l.strip() for l in reply_text.strip().split("\n") if l.strip()]

    # 方案1: 尝试按 "字段名: 值" 格式解析
    named_values = {}
    remaining = []
    for line in lines:
        # 匹配 "字段名: 值" 格式
        m = re.match(r"^(.+?)[：:]\s*(.*)", line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            named_values[key] = val
        else:
            remaining.append(line)

    if named_values:
        # 按字段名匹配
        for f in fields:
            fname = f["显示名"]
            fkey = f["字段"]
            # 尝试精确匹配和包含匹配
            if fname in named_values:
                result[fkey] = named_values[fname]
            else:
                # 从字段名中提取关键词匹配
                matched = False
                for nk, nv in named_values.items():
                    if fname[:2] in nk or fkey.replace("_", "") in nk:
                        result[fkey] = nv
                        matched = True
                        break
                if not matched and f.get("必填"):
                    return None  # 必填字段缺失
                if not matched:
                    result[fkey] = f.get("默认", "")
        return result

    # 方案2: 位置解析（用户按顺序回复，每行一个值）
    for i, f in enumerate(fields):
        if i < len(remaining):
            val = remaining[i]
            if val:
                result[f["字段"]] = val
            else:
                result[f["字段"]] = f.get("默认", "")
        else:
            result[f["字段"]] = f.get("默认", "")

    # 检查必填字段
    for f in fields:
        if f.get("必填") and not result.get(f["字段"]):
            return None

    return result


# ================================
# 任务执行器
# ================================
# 适配器加载
# ================================
def load_adapter(adapter_name):
    """加载适配器模块，返回 (prepare_input, process_output)"""
    if not adapter_name:
        return None, None
    try:
        mod = __import__(f"adapters.{adapter_name}", fromlist=[adapter_name])
        return getattr(mod, "prepare_input", None), getattr(mod, "process_output", None)
    except (ImportError, AttributeError) as e:
        print(f"  [警告] 加载适配器失败: {adapter_name} - {e}", flush=True)
        return None, None


# ================================
def execute_task(task_id, task):
    """执行任务：所有任务走统一的多阶段执行"""
    stages = task.get("exec_plan", [])
    execute_multi_stage(task_id, task, stages)


def run_subprocess(cmd, work_dir, stdin_data=None):
    """运行子进程，实时输出到控制台，返回 (returncode, stdout_lines)
       支持通过 stdin 传入数据。"""
    print(f"  [执行] {' '.join(cmd)}", flush=True)

    if stdin_data:
        proc = subprocess.Popen(cmd, cwd=str(work_dir),
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout_bytes, _ = proc.communicate(input=stdin_data.encode("utf-8"), timeout=3600)
        text = stdout_bytes.decode("utf-8", errors="replace")
        stdout_lines = []
        for line in text.split("\n"):
            line = line.rstrip()
            if line:
                print(f"    {line}", flush=True)
                stdout_lines.append(line)
        returncode = proc.returncode
    else:
        proc = subprocess.Popen(cmd, cwd=str(work_dir),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        stdout_lines = []
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                print(f"    {text}", flush=True)
                stdout_lines.append(text)
        proc.stdout.close()
        returncode = proc.wait()
    return returncode, stdout_lines


def check_output_failure(stdout_lines):
    """检查输出中是否有 ERROR: 开头行"""
    if not stdout_lines:
        return False
    return any(line.startswith("ERROR:") for line in stdout_lines)


def prepare_cmd(cmd):
    """准备执行命令：python 加 -X utf8，非 python 解析相对路径"""
    work_dir = SCRIPT_DIR
    if not cmd:
        return cmd, work_dir
    program = cmd[0]
    if program == "python":
        cmd = list(cmd)
        cmd.insert(1, "-X")
        cmd.insert(2, "utf8")
    else:
        program_path = SCRIPT_DIR / program
        if program_path.exists():
            cmd = list(cmd)
            cmd[0] = str(program_path)
    return cmd, work_dir


def update_stage_status(task_id, stage_name, status, **extra):
    """更新指定阶段的执行状态"""
    data = load_tasks()
    if task_id not in data["tasks"]:
        return
    task = data["tasks"][task_id]
    stage_results = task.setdefault("stage_results", {})
    if stage_name not in stage_results:
        stage_results[stage_name] = {}
    stage_results[stage_name]["status"] = status
    for k, v in extra.items():
        stage_results[stage_name][k] = v
    save_tasks(data)


def execute_multi_stage(task_id, task, stages):
    """执行多阶段任务：依次执行每个阶段，调用适配器，阶段间通过 context 共享变量"""
    chat_id = task.get("chat_id", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    update_task_status(task_id, "running", started_at=now)
    fs.send_text(chat_id, f"🔄 任务 [{task_id}] {task['type_name']} 开始执行（共 {len(stages)} 个阶段）")

    # 阶段间上下文：表单字段 + 类型配置 + 阶段间动态变量
    context = {
        "task_id": task_id,
        "fields": task.get("fields", {}),
        "type_config": task.get("type_config", {}),
    }

    all_ok = True
    for stage in stages:
        stage_name = stage.get("阶段名", "未知")
        cmd = stage.get("命令行", [])
        fail_strategy = stage.get("失败策略", "中止")
        post_adapter = stage.get("后处理适配器", "")
        pre_adapter = stage.get("输入准备适配器", "")

        # 跳过已成功的阶段
        current_results = task.get("stage_results", {})
        prev_status = current_results.get(stage_name, {}).get("status", "")
        if prev_status == "success":
            print(f"  [跳过] 阶段「{stage_name}」已成功", flush=True)
            continue

        # 1. 输入准备适配器（阶段执行前）
        if pre_adapter:
            pre_fn, _ = load_adapter(pre_adapter)
            if pre_fn:
                context = pre_fn(context)

        # 检查适配器是否要求跳过此阶段
        if context.get("skip_publish", False):
            print(f"  [跳过] 阶段「{stage_name}」被适配器跳过", flush=True)
            fs.send_text(chat_id, f"  ⏭️ 阶段「{stage_name}」条件不满足，跳过")
            # 不标记失败也不标记成功，保持之前的 pending 状态
            continue

        print(f"\n  === 阶段: {stage_name} ===", flush=True)
        fs.send_text(chat_id, f"  ⏳ 阶段「{stage_name}」开始...")

        update_stage_status(task_id, stage_name, "running",
                            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        if not cmd:
            update_stage_status(task_id, stage_name, "failed", error="命令行空",
                                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            fs.send_text(chat_id, f"  ❌ 阶段「{stage_name}」失败: 命令行空")
            all_ok = False
            if fail_strategy == "中止":
                break
            continue

        try:
            cmd, work_dir = prepare_cmd(cmd)
            stdin_data = context.get("stdin_data", None)
            stdout_raw = "\n".join(context.get("stdout_lines", []))
            returncode, stdout_lines = run_subprocess(cmd, work_dir, stdin_data=stdin_data)
            has_error = check_output_failure(stdout_lines)
        except subprocess.TimeoutExpired:
            update_stage_status(task_id, stage_name, "failed", error="执行超时",
                                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            fs.send_text(chat_id, f"  ⏰ 阶段「{stage_name}」执行超时")
            all_ok = False
            if fail_strategy == "中止":
                break
            continue
        except Exception as e:
            update_stage_status(task_id, stage_name, "failed", error=str(e),
                                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            fs.send_text(chat_id, f"  ❌ 阶段「{stage_name}」异常: {str(e)[:200]}")
            all_ok = False
            if fail_strategy == "中止":
                break
            continue

        # 2. 后处理适配器（阶段执行后）
        if post_adapter:
            _, post_fn = load_adapter(post_adapter)
            if post_fn:
                context = post_fn("\n".join(stdout_lines), context)

        stage_ok = (returncode == 0 and not has_error)
        if stage_ok:
            update_stage_status(task_id, stage_name, "success",
                                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            fs.send_text(chat_id, f"  ✅ 阶段「{stage_name}」完成")
        else:
            last_lines = "\n".join(stdout_lines[-30:]) if stdout_lines else "(无输出)"
            error = last_lines[:500]
            update_stage_status(task_id, stage_name, "failed", error=error,
                                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            fs.send_text(chat_id, f"  ❌ 阶段「{stage_name}」失败:\n{error[:300]}")
            all_ok = False
            if fail_strategy == "中止":
                break

    # 汇总结果
    if all_ok:
        update_task_status(task_id, "success", finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        fs.send_text(chat_id, f"✅ 任务 [{task_id}] {task['type_name']} 全部阶段完成！")
        print(f"  [完成] {task_id}", flush=True)
    else:
        update_task_status(task_id, "failed", error="部分阶段失败",
                           finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        fs.send_text(chat_id, f"⚠️ 任务 [{task_id}] 部分阶段失败，详情见任务状态")
        print(f"  [失败] {task_id} (部分阶段失败)", flush=True)


# ================================
# 消息路由 / 命令解析
# ================================
COMMAND_PATTERNS = {
    "删除全部": ["删除全部任务", "清空任务", "删除所有任务"],
    "任务列表": ["任务列表", "列出任务", "所有任务"],
    "查询": ["查询任务", "任务状态", "查看任务"],
    "登记": ["登记任务", "新建任务", "创建任务"],
    "删除": ["删除任务", "移除任务"],
    "取消": ["取消任务"],
    "重试": ["重试任务", "重新执行"],
    "帮助": ["帮助", "命令", "/help"],
}


def detect_intent(text):
    """检测用户消息意图"""
    text_lower = text.strip().lower()
    for intent, keywords in COMMAND_PATTERNS.items():
        for kw in keywords:
            if kw in text_lower:
                return intent
    return None


def extract_task_id(text):
    """从文本中提取任务ID (T-YYYYMMDD-NNN)"""
    m = re.search(r"T-\d{8}-\d{3}", text)
    return m.group(0) if m else None


# ================================
# 任务调度器
# ================================
SCHEDULER_POLL_INTERVAL = 10  # 秒


def scheduler_loop(data_lock, task_queue):
    """定时检查并执行到期任务"""
    while True:
        try:
            data = load_tasks()
            now = datetime.now()
            for task_id, task in data.get("tasks", {}).items():
                if task.get("status") != "pending":
                    continue
                exec_at_str = task.get("execute_at", "")
                if not exec_at_str:
                    continue
                try:
                    exec_at = datetime.strptime(exec_at_str, "%Y-%m-%d %H:%M")
                    if now >= exec_at:
                        # 提交到执行队列
                        task_queue.put((task_id, copy.deepcopy(task)))
                        print(f"  [调度] {task_id} 到期，加入执行队列")
                except ValueError:
                    pass  # 时间格式不对，忽略
        except Exception as e:
            print(f"  [调度器错误] {e}")
        time.sleep(SCHEDULER_POLL_INTERVAL)


# ================================
# 消息处理
# ================================
def handle_message(msg, user_states, task_types, chat_id):
    """处理单条飞书消息"""
    text = fs.extract_display_text(msg)
    sender_label = fs.format_sender_label(msg)

    # 忽略自己(BOT)发的消息
    if sender_label == "BOT":
        return None

    print(f"  [消息] {sender_label}: {text[:60]}")

    # 获取当前用户状态
    state_info = user_states.get(chat_id, {"state": "idle", "context": {}})
    current_state = state_info["state"]
    context = state_info["context"]

    # --- 等待表单回复 ---
    if current_state == "waiting_form":
        selected_type = context.get("selected_type")
        if not selected_type:
            user_states[chat_id] = {"state": "idle", "context": {}}
            fs.send_text(chat_id, "❌ 内部错误：未找到任务类型的会话上下文，请重新输入「登记任务」")
            return None

        # 解析表单回复
        fields = parse_form_reply(text, selected_type)
        if fields is None:
            # 必填字段缺失
            fs.send_text(chat_id, "❌ 请填写所有必填字段（带*的），并使用「字段名: 值」格式。\n请重新发送「登记任务」开始")
            user_states[chat_id] = {"state": "idle", "context": {}}
            return None

        # 创建任务
        task_id, task = create_task(selected_type, fields, chat_id, sender_label)
        if task_id:
            fs.send_text(chat_id, (
                f"✅ 任务已登记！\n"
                f"  任务ID: {task_id}\n"
                f"  类型: {selected_type['名称']}\n"
                f"  执行时间: {task.get('execute_at', '立即')}\n"
                f"  状态: pending\n\n"
                f"输入「查询任务 {task_id}」查看状态"
            ))
            print(f"  [登记] {task_id} ({selected_type['标识']})")
        else:
            fs.send_text(chat_id, "❌ 任务登记失败，请稍后重试")

        user_states[chat_id] = {"state": "idle", "context": {}}
        return {"action": "task_created", "task_id": task_id}

    # --- 等待任务类型选择 ---
    if current_state == "waiting_task_type":
        # 用户选择了编号或任务类型名称
        text_stripped = text.strip()
        selected_type = None

        # 按编号选择
        if text_stripped.isdigit():
            idx = int(text_stripped) - 1
            if 0 <= idx < len(task_types):
                selected_type = task_types[idx]
        else:
            # 按名称/标识匹配
            selected_type = find_task_type(task_types, text_stripped)

        if not selected_type:
            # 列出可选类型
            lines = ["❌ 未找到该任务类型，请选择："]
            for i, tt in enumerate(task_types):
                lines.append(f"  {i+1}. {tt['名称']} ({tt.get('标识', '')})")
            fs.send_text(chat_id, "\n".join(lines))
            return None

        # 发送任务表单
        form_text = build_form_text(selected_type)
        fs.send_text(chat_id, form_text)
        user_states[chat_id] = {
            "state": "waiting_form",
            "context": {"selected_type": selected_type}
        }
        return {"action": "form_sent", "task_type": selected_type["标识"]}

    # --- 空闲状态：检测命令 ---
    intent = detect_intent(text)
    if not intent:
        return None

    if intent == "帮助":
        help_text = (
            "📋 飞书任务引擎 - 可用命令\n\n"
            "  「登记任务」           - 登记新任务（列出所有类型）\n"
            "  「登记任务 编号」     - 直接登记指定类型的任务\n"
            "  「登记任务 名称」     - 按名称直接登记任务\n"
            "  「任务列表」           - 列出所有任务\n"
            "  「查询任务 T-ID」     - 查看任务状态\n"
            "  「取消任务 T-ID」     - 归档任务（保留记录）\n"
            "  「删除任务 T-ID」     - 彻底删除单个任务\n"
            "  「删除全部任务」      - 清空所有任务\n"
            "  「重试任务 T-ID」     - 重试失败任务\n"
            "  「帮助」              - 查看此帮助"
        )
        fs.send_text(chat_id, help_text)
        return {"action": "help"}

    if intent == "登记":
        if not task_types:
            fs.send_text(chat_id, "⚠️ 没有可用的任务类型（配置文件为空）")
            return None

        # 尝试从消息中提取任务类型（支持：编号、标识、名称）
        text_clean = text.strip()
        # 去掉"登记任务"等前缀
        for kw in COMMAND_PATTERNS["登记"]:
            if text_clean.startswith(kw):
                text_clean = text_clean[len(kw):].strip()
                break

        selected_type = None
        if text_clean:
            # 尝试按编号匹配
            if text_clean.isdigit():
                idx = int(text_clean) - 1
                if 0 <= idx < len(task_types):
                    selected_type = task_types[idx]
            else:
                # 按标识或名称匹配
                selected_type = find_task_type(task_types, text_clean)

        if selected_type:
            # 直接发送表单
            form_text = build_form_text(selected_type)
            fs.send_text(chat_id, form_text)
            user_states[chat_id] = {
                "state": "waiting_form",
                "context": {"selected_type": selected_type}
            }
            return {"action": "form_sent", "task_type": selected_type["标识"]}

        # 原来的做法：列出任务类型供选择
        lines = ["📝 请选择任务类型："]
        for i, tt in enumerate(task_types):
            lines.append(f"  {i+1}. {tt['名称']}")
            desc = tt.get("描述", "")
            if desc:
                lines.append(f"     {desc}")
        lines.append("\n回复编号或类型名称")
        fs.send_text(chat_id, "\n".join(lines))
        user_states[chat_id] = {
            "state": "waiting_task_type",
            "context": {}
        }
        return {"action": "task_type_list"}

    if intent == "任务列表":
        data = load_tasks()
        all_tasks = data.get("tasks", {})
        if not all_tasks:
            fs.send_text(chat_id, "📭 目前没有任何任务记录")
            return {"action": "task_list"}

        # 按状态分组
        groups = {"pending": [], "running": [], "success": [], "failed": [], "cancelled": []}
        for tid, t in all_tasks.items():
            s = t.get("status", "pending")
            groups.setdefault(s, []).append((tid, t))

        status_icon = {"pending": "⏳", "running": "🔄", "success": "✅", "failed": "❌", "cancelled": "🗑️"}
        lines = [f"📋 任务列表（共 {len(all_tasks)} 个）\n"]
        for status_name in ["pending", "running", "success", "failed", "cancelled"]:
            items = groups.get(status_name, [])
            if not items:
                continue
            icon = status_icon.get(status_name, "❓")
            lines.append(f"  {icon} {status_name} ({len(items)}):")
            for tid, t in items:
                type_name = t.get("type_name", "?")
                created = t.get("created_at", "?")
                lines.append(f"    {tid} [{type_name}] @{created}")
            lines.append("")

        reply = "\n".join(lines).rstrip()
        # 分片发送，避免飞书消息超长
        if len(reply) > 1500:
            fs.send_text(chat_id, reply[:1500] + "\n\n⚠️ 任务过多，只显示部分")
        else:
            fs.send_text(chat_id, reply)
        return {"action": "task_list"}

    if intent == "查询":
        task_id = extract_task_id(text)
        if not task_id:
            fs.send_text(chat_id, "❌ 请指定任务ID，如「查询任务 T-20260626-001」")
            return None

        data = load_tasks()
        task = data.get("tasks", {}).get(task_id)
        if not task:
            fs.send_text(chat_id, f"❌ 未找到任务: {task_id}")
            return None

        status_icon = {"pending": "⏳", "running": "🔄", "success": "✅", "failed": "❌"}
        icon = status_icon.get(task["status"], "❓")
        reply = (
            f"{icon} 任务 {task_id}\n"
            f"  类型: {task.get('type_name', '未知')}\n"
            f"  状态: {task['status']}\n"
            f"  创建时间: {task.get('created_at', 'N/A')}\n"
            f"  执行时间: {task.get('execute_at', 'N/A')}\n"
        )
        if task.get("started_at"):
            reply += f"  开始执行: {task['started_at']}\n"
        if task.get("finished_at"):
            reply += f"  完成时间: {task['finished_at']}\n"
        if task.get("result"):
            reply += f"  结果: {task['result']}\n"
        if task.get("error"):
            reply += f"  错误: {task['error'][:200]}\n"

        # 显示表单要素
        fields = task.get("fields", {})
        if fields:
            reply += f"\n  登记信息:\n"
            for k, v in fields.items():
                if v:
                    display_v = v[:50] + "..." if len(v) > 50 else v
                    reply += f"    {k}: {display_v}\n"

        # 显示阶段进度（多阶段任务）
        stage_results = task.get("stage_results", {})
        if stage_results:
            stage_icon = {"pending": "⏳", "running": "🔄", "success": "✅", "failed": "❌"}
            reply += f"\n  📋 执行进度:\n"
            for sname, sresult in stage_results.items():
                s_status = sresult.get("status", "pending")
                s_icon = stage_icon.get(s_status, "❓")
                reply += f"    {s_icon} {sname}: {s_status}\n"

        fs.send_text(chat_id, reply.strip())
        return {"action": "task_status"}

    if intent == "取消":
        task_id = extract_task_id(text)
        if not task_id:
            fs.send_text(chat_id, "❌ 请指定任务ID，如「取消任务 T-20260626-001」")
            return None

        data = load_tasks()
        if task_id not in data.get("tasks", {}):
            fs.send_text(chat_id, f"❌ 未找到任务: {task_id}")
            return None

        task = data["tasks"][task_id]
        if task["status"] == "running":
            fs.send_text(chat_id, f"⚠️ 任务 {task_id} 正在执行中，无法取消")
            return None
        if task["status"] == "cancelled":
            fs.send_text(chat_id, f"ℹ️ 任务 {task_id} 已处于取消状态")
            return None

        update_task_status(task_id, "cancelled", finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        fs.send_text(chat_id, f"🗑️ 任务 {task_id} 已取消")
        return {"action": "task_cancelled"}

    if intent == "删除全部":
        count = delete_all_tasks()
        if count > 0:
            fs.send_text(chat_id, f"🗑️ 已清空全部 {count} 个任务")
            print(f"  [清空] 删除了 {count} 个任务", flush=True)
        else:
            fs.send_text(chat_id, "📭 任务列表已经是空的")
        return {"action": "tasks_cleared"}

    if intent == "删除":
        task_id = extract_task_id(text)
        if not task_id:
            fs.send_text(chat_id, "❌ 请指定任务ID，如「删除任务 T-20260626-001」")
            return None

        data = load_tasks()
        if task_id not in data.get("tasks", {}):
            fs.send_text(chat_id, f"❌ 未找到任务: {task_id}")
            return None

        if delete_task(task_id):
            fs.send_text(chat_id, f"🗑️ 任务 {task_id} 已彻底删除")
            print(f"  [删除] {task_id}", flush=True)
            return {"action": "task_deleted"}
        else:
            fs.send_text(chat_id, f"❌ 删除任务 {task_id} 失败")
            return None

    if intent == "重试":
        task_id = extract_task_id(text)
        if not task_id:
            fs.send_text(chat_id, "❌ 请指定任务ID，如「重试任务 T-20260626-001」")
            return None

        data = load_tasks()
        if task_id not in data.get("tasks", {}):
            fs.send_text(chat_id, f"❌ 未找到任务: {task_id}")
            return None

        task = data["tasks"][task_id]
        if task["status"] != "failed":
            fs.send_text(chat_id, f"⚠️ 只有失败状态的任务可以重试（当前: {task['status']}）")
            return None

        # 多阶段任务：重置只重置失败的阶段，已成功的阶段跳过
        stage_results = task.get("stage_results", {})
        if stage_results:
            # 只重置 failed 或 unknown 的阶段
            for sname, sresult in stage_results.items():
                if sresult.get("status") in ("failed", "pending"):
                    sresult["status"] = "pending"
                    sresult["started_at"] = None
                    sresult["finished_at"] = None
                    sresult["error"] = None
            update_task_status(task_id, "pending", error=None, finished_at=None, stage_results=stage_results)
            msg = f"🔄 任务 {task_id} 已重置（跳过已成功的阶段），将重新执行"
        else:
            # 单阶段任务：完整重置
            update_task_status(task_id, "pending", error=None, finished_at=None)
            msg = f"🔄 任务 {task_id} 已重置，将重新执行"

        fs.send_text(chat_id, msg)
        return {"action": "task_retry"}

    return None


# ================================
# 引擎主循环
# ================================
def run_engine(chat_id, task_types, identity="bot"):
    """任务引擎主循环"""
    print("=" * 50, flush=True)
    print("  飞书任务调度引擎启动", flush=True)
    print(f"  聊天: {chat_id}", flush=True)
    print(f"  身份: {identity}", flush=True)
    print(f"  任务配置文件: {TASK_CONFIG_FILE.name}", flush=True)
    print("=" * 50, flush=True)
    print(flush=True)

    # 加载已有任务
    data = load_tasks()
    pending = sum(1 for t in data.get("tasks", {}).values() if t["status"] == "pending")
    running = sum(1 for t in data.get("tasks", {}).values() if t["status"] == "running")
    print(f"  已加载 {len(data.get('tasks', {}))} 个任务 (pending: {pending}, running: {running})", flush=True)
    print(flush=True)

    # 对话状态：chat_id → {"state": "idle"/"waiting_task_type"/"waiting_form", "context": {}}
    user_states = {}

    # 消息去重：启动时不加载历史消息，只处理启动后的新消息
    known_msg_ids = set()
    startup_done = False  # 标记：首次轮询已跳过历史消息

    # 任务执行队列
    task_queue = Queue()

    # 启动调度器线程
    scheduler_thread = threading.Thread(
        target=scheduler_loop,
        args=(None, task_queue),
        daemon=True
    )
    scheduler_thread.start()

    print("  发送启动通知...", flush=True)
    try:
        # 构造启动消息：帮助 + 当前任务概况
        all_tasks = data.get("tasks", {})
        startup_msg = "🤖 飞书任务引擎已启动！\n\n"
        startup_msg += "📋 可用命令：\n"
        startup_msg += "  「登记任务」           - 登记新任务（列出所有类型）\n"
        startup_msg += "  「登记任务 编号」      - 直接登记指定类型的任务\n"
        startup_msg += "  「登记任务 名称」      - 按名称直接登记任务\n"
        startup_msg += "  「任务列表」           - 列出所有任务\n"
        startup_msg += "  「查询任务 T-ID」      - 查看任务状态\n"
        startup_msg += "  「取消任务 T-ID」      - 归档任务（保留记录）\n"
        startup_msg += "  「删除任务 T-ID」      - 彻底删除单个任务\n"
        startup_msg += "  「删除全部任务」       - 清空所有任务\n"
        startup_msg += "  「重试任务 T-ID」      - 重试失败任务\n"
        startup_msg += "  「帮助」               - 查看帮助\n\n"

        if all_tasks:
            pending = sum(1 for t in all_tasks.values() if t["status"] == "pending")
            running = sum(1 for t in all_tasks.values() if t["status"] == "running")
            success = sum(1 for t in all_tasks.values() if t["status"] == "success")
            failed = sum(1 for t in all_tasks.values() if t["status"] == "failed")
            startup_msg += f"📊 当前共 {len(all_tasks)} 个任务：\n"
            startup_msg += f"  ⏳ 待执行: {pending}  🔄 运行中: {running}\n"
            startup_msg += f"  ✅ 已完成: {success}  ❌ 已失败: {failed}"
        else:
            startup_msg += "📭 暂无任务记录"

        ok, _ = fs.send_text(chat_id, startup_msg.strip())
        print(f"  启动通知 {'已发送' if ok else '发送失败'}", flush=True)
    except Exception as e:
        print(f"  启动通知发送异常: {e}", flush=True)
    print(flush=True)

    # 主循环
    poll_interval = 3
    while True:
        try:
            # 1. 轮询新消息
            ok, data = fs.list_messages(chat_id, identity, page_size=10, order="desc")
            if ok:
                messages = data.get("data", {}).get("messages", [])

                if not startup_done:
                    # 首次轮询：把所有消息ID记作已读，不处理任何历史消息
                    for msg in messages:
                        known_msg_ids.add(msg.get("message_id", ""))
                    startup_done = True
                    continue

                new_msgs = []
                for msg in messages:
                    msg_id = msg.get("message_id", "")
                    if msg_id not in known_msg_ids:
                        known_msg_ids.add(msg_id)
                        new_msgs.append(msg)

                if new_msgs:
                    new_msgs.sort(key=lambda m: m.get("create_time", ""))
                    for msg in new_msgs:
                        try:
                            handle_message(msg, user_states, task_types, chat_id)
                        except Exception as e:
                            print(f"  [处理消息异常] {e}")

            # 2. 执行待执行任务
            executed = []
            while not task_queue.empty():
                try:
                    task_id, task = task_queue.get_nowait()
                    # 检查任务是否还是 pending 状态（可能被取消）
                    current_data = load_tasks()
                    if task_id in current_data.get("tasks", {}):
                        if current_data["tasks"][task_id]["status"] == "pending":
                            executed.append((task_id, task))
                except Empty:
                    break

            # 在单独线程中执行任务（避免阻塞主循环）
            for task_id, task in executed:
                t = threading.Thread(
                    target=execute_task,
                    args=(task_id, task),
                    daemon=True
                )
                t.start()

        except KeyboardInterrupt:
            print("\n引擎停止")
            fs.send_text(chat_id, "🛑 飞书任务引擎已停止")
            break
        except Exception as e:
            print(f"  [主循环异常] {e}")

        time.sleep(poll_interval)


# ================================
# 主入口
# ================================
def main():
    parser = argparse.ArgumentParser(
        description="飞书任务调度引擎",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python task_engine.py                     # 前台运行
  python task_engine.py --daemon            # 后台运行
        """
    )
    parser.add_argument("--daemon", action="store_true", help="后台运行模式")
    parser.add_argument("--to", help="指定飞书聊天对象（覆盖默认）")
    parser.add_argument("--chat-id", help="指定 chat_id（覆盖默认）")
    parser.add_argument("--as", dest="identity_type",
                        choices=["bot", "user"], help="身份 (默认bot)")
    args = parser.parse_args()

    # 加载任务类型配置
    task_types = load_task_configs()
    print(f"已加载 {len(task_types)} 个任务类型:")
    for tt in task_types:
        print(f"  - {tt['名称']} ({tt.get('标识', '')})")

    # 获取飞书聊天目标
    fs_config = fs.load_config()
    chat_id, chat_name = fs.resolve_chat_id(fs_config, args)
    identity = args.identity_type or fs_config.get("默认身份", "bot")

    print(f"聊天目标: {chat_name} [{chat_id}]")
    print(f"身份: {identity}")
    print()

    # 启动引擎
    run_engine(chat_id, task_types, identity)


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
读取 wf.json 配置文件，执行自动化工作流

功能:
1. 读取 wf.json 获取进程名和工作流配置
2. 截取目标进程窗口并保存到进程名目录
3. 遍历工作流步骤，使用模板匹配定位点位并执行动作
"""

import sys
import io
import os
import time
import ctypes
import json
import argparse

# 修复 Windows 终端中文编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)

import win32gui
import win32con
import win32process
import win32api
import psutil
from PIL import ImageGrab
import pyautogui
import pyperclip

# 导入模板匹配模块
from template_matcher import find_text, draw_results


# ===== 配置文件路径 =====
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_WF = os.path.join(SCRIPT_DIR, "wf.json")


def load_config(config_path):
    """读取 JSON 配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_window_by_process(target_proc):
    """通过进程名查找对应的可见窗口句柄"""
    found = []
    target_name = target_proc.lower().replace(".exe", "")

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if psutil.pid_exists(pid):
                proc_name = psutil.Process(pid).name().lower().replace(".exe", "")
                if proc_name == target_name:
                    found.append((hwnd, title, pid))
        except Exception:
            pass

    win32gui.EnumWindows(callback, None)
    return found


def bring_to_front_and_maximize(hwnd):
    """将窗口前置并最大化"""
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
    )
    time.sleep(0.1)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    time.sleep(0.2)
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    time.sleep(0.2)
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
    )
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)


def capture_and_save(hwnd, save_path):
    """截取窗口并保存"""
    rect = win32gui.GetWindowRect(hwnd)
    img = ImageGrab.grab(bbox=rect)
    img.save(save_path)
    return save_path


def scroll_screen(scroll_value, hwnd):
    """
    按像素滚动屏幕
    正数: 向上滚动，负数: 向下滚动
    每 1 个单位 = 半屏（窗口高度 / 2 像素）

    使用 win32api mouse_event MOUSEEVENTF_WHEEL 发送滚轮事件。
    每次发送 WHEEL_DELTA(120) = 1 次完整滚轮点击。
    """
    MOUSEEVENTF_WHEEL = 0x0800
    WHEEL_DELTA = 120

    # 获取窗口高度
    rect = win32gui.GetWindowRect(hwnd)
    window_height = rect[3] - rect[1]
    half_screen_pixels = window_height // 2

    # 计算总滚动像素
    total_pixels = scroll_value * half_screen_pixels

    # 获取系统滚轮设置: 每次滚轮点击滚动多少行
    try:
        buf = ctypes.c_int(0)
        ctypes.windll.user32.SystemParametersInfoW(104, 0, ctypes.byref(buf), 0)
        lines_per_notch = max(1, buf.value)
    except Exception:
        lines_per_notch = 3

    # 每行约 20 像素 → 每次滚轮点击约滚动 pixels_per_notch 像素
    pixels_per_notch = max(1, lines_per_notch * 20)

    # 计算需要多少次完整滚轮点击 + 余量
    num_notches = abs(total_pixels) // pixels_per_notch
    remainder_pixels = abs(total_pixels) % pixels_per_notch

    # 方向: 正数向上(正值), 负数向下(负值)
    direction = 1 if total_pixels > 0 else -1

    print(f"  [滚屏参数] 窗口高度={window_height}px, 半屏={half_screen_pixels}px")
    print(f"  [滚屏参数] 目标滚动={total_pixels}px, 每次滚轮≈{pixels_per_notch}px ({lines_per_notch}行×20px)")
    print(f"  [滚屏参数] 需发送 {num_notches} 次完整滚轮 + 余量{remainder_pixels}px")

    # 发送完整滚轮点击: 每次发 WHEEL_DELTA(120) * direction
    for i in range(num_notches):
        ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, WHEEL_DELTA * direction, 0)
        time.sleep(0.03)

    # 发送余量 (按比例换算为 partial delta)
    if remainder_pixels > 0:
        partial_delta = int(WHEEL_DELTA * remainder_pixels / pixels_per_notch)
        if partial_delta > 0:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, partial_delta * direction, 0)
            time.sleep(0.03)


def resolve_point(match, select_point):
    """
    根据选点参数从匹配结果中计算目标坐标。

    参数:
        match (dict): find_text 返回的单个匹配结果
        select_point: 选点配置，支持:
            None / "" / "中心点"  → 匹配区域中心点（默认）
            "左上角"             → 匹配区域左上角
            "左下角"             → 匹配区域左下角
            "右上角"             → 匹配区域右上角
            "右下角"             → 匹配区域右下角
            {"x": 10, "y": -5}  → 相对左上角偏移：右移10px、上移5px

    返回:
        (x, y) 目标坐标
    """
    x, y = match["左上角"]
    w, h = match["尺寸"]

    if select_point is None or select_point == "" or select_point == "中心点":
        return match["中心点"]
    elif select_point == "左上角":
        return (x, y)
    elif select_point == "左下角":
        return (x, y + h)
    elif select_point == "右上角":
        return (x + w, y)
    elif select_point == "右下角":
        return (x + w, y + h)
    elif isinstance(select_point, dict):
        return (x + select_point.get("x", 0), y + select_point.get("y", 0))
    else:
        print(f"  [警告] 未知选点值 '{select_point}'，回退到中心点")
        return match["中心点"]


def execute_workflow(config):
    """
    执行工作流:
    1. 查找目标进程窗口
    2. 前置并最大化
    3. 截屏保存到进程名目录
    4. 遍历工作流步骤，定位点位并执行动作
    """
    process_name = config["进程名"]
    workflow = config.get("工作流", [])

    print(f"目标进程: {process_name}")
    print(f"工作流步骤数: {len(workflow)}")
    print("-" * 50)

    # 1. 查找进程窗口
    windows = find_window_by_process(process_name)
    if not windows:
        print(f"未找到 {process_name} 的窗口，请确认进程正在运行")
        success = False
        return success

    hwnd, title, pid = windows[0]
    print(f"找到窗口: {title} (句柄 {hwnd}, PID {pid})")

    # 2. 前置并最大化
    print("正在前置并最大化窗口...")
    bring_to_front_and_maximize(hwnd)
    time.sleep(0.5)

    # 3. 截屏并保存到进程名目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    process_dir = os.path.join(script_dir, process_name)
    os.makedirs(process_dir, exist_ok=True)
    screenshot_path = os.path.join(process_dir, f"{process_name}.png")
    print(f"正在截屏: {screenshot_path}")
    capture_and_save(hwnd, screenshot_path)
    print(f"截图已保存: {screenshot_path}")

    # 4. 遍历工作流步骤
    print("\n开始执行工作流...")
    print("=" * 50)
    success = True

    for step in workflow:
        step_num = step.get("步骤", "?")
        desc = step.get("描述", "")
        template_file = step.get("点位图", "")
        action = step.get("动作", "")
        text_input = step.get("文本输入", "")
        wait_after = step.get("点击后等待", 0.5)
        screenshot_flag = str(step.get("截屏标志", "0"))
        scroll = step.get("滚屏", 0)
        select_point = step.get("选点", "中心点")
        on_fail = step.get("失败处理", "跳过")

        print(f"\n步骤 {step_num}: {desc}")
        print(f"  点位图:   {template_file if template_file else '(空，跳过匹配)'}")
        print(f"  选点:     {select_point if select_point else '中心点(默认)'}")
        print(f"  动作:     {action}")
        print(f"  文本输入: {text_input if text_input else '(无)'}")
        print(f"  截屏标志: {screenshot_flag}")
        print(f"  滚屏:     {scroll if scroll else '(无)'}")
        print(f"  失败处理: {on_fail}")

        # 4.0 必要点位：前置门控，等待指定元素出现后再继续
        required_point = step.get("必要点位", None)
        if required_point:
            if not isinstance(required_point, list) or len(required_point) < 1:
                print(f"  [错误] 必要点位配置格式不正确: {required_point}")
                print("\n" + "=" * 50)
                print("工作流因必要点位配置错误而终止！")
                success = False
                return success

            req_template = required_point[0]
            req_max_retry = required_point[1] if len(required_point) > 1 else 1
            req_template_path = os.path.join(process_dir, req_template)

            print(f"  必要点位: 模板={req_template}, 最大重试={req_max_retry}")

            if not os.path.exists(req_template_path):
                print(f"  [错误] 必要点位模板文件不存在: {req_template_path}")
                print("\n" + "=" * 50)
                print("工作流因必要点位模板缺失而终止！")
                success = False
                return success

            req_count = 0
            req_matched = False
            while True:
                print(f"  [必要点位] 第 {req_count + 1} 次判断，等待 10 秒...")
                time.sleep(10)

                # 重新截屏刷新画面
                capture_and_save(hwnd, screenshot_path)

                # 匹配必要点位
                req_results = find_text(screenshot_path, req_template_path, threshold=0.8)
                if req_results:
                    print(f"  [必要点位] 匹配成功! 置信度 {req_results[0]['置信度']:.4f}, 继续执行本步骤")
                    req_matched = True
                    break

                req_count += 1
                print(f"  [必要点位] 未匹配, 已重试 {req_count}/{req_max_retry}")

                if req_count > req_max_retry:
                    print(f"  [必要点位] 重试次数超限({req_count} > {req_max_retry}), 终止脚本")
                    print("\n" + "=" * 50)
                    print("工作流因必要点位未出现而终止！")
                    success = False
                    return success

            if not req_matched:
                success = False
                return success

        cx, cy = None, None

        # 4.1 如果点位图不为空，执行模板匹配
        if template_file:
            template_path = os.path.join(process_dir, template_file)
            if not os.path.exists(template_path):
                print(f"  [失败] 点位图文件不存在: {template_path}")
                if on_fail == "中止":
                    print("  → 失败策略为「中止」，终止工作流")
                    print("\n" + "=" * 50)
                    print("工作流因步骤失败而终止！")
                    success = False
                    return success
                continue

            print(f"  正在匹配点位...")
            results = find_text(screenshot_path, template_path, threshold=0.8)

            if not results:
                print(f"  [失败] 未找到匹配的点位")
                if on_fail == "中止":
                    print("  → 失败策略为「中止」，终止工作流")
                    print("\n" + "=" * 50)
                    print("工作流因步骤失败而终止！")
                    success = False
                    return success
                continue

            best = results[0]
            cx, cy = resolve_point(best, select_point)
            print(f"  匹配成功: 左上角{best['左上角']}, 尺寸{best['尺寸']}, 置信度 {best['置信度']:.4f}")
            print(f"  选点结果: ({cx}, {cy})")

            # 移动鼠标到点位
            print(f"  移动鼠标到: ({cx}, {cy})")
            pyautogui.moveTo(cx, cy)
            time.sleep(0.2)
        else:
            print(f"  点位图为空，跳过点位查找")

        # 4.2 执行动作
        if action == "单击" and cx is not None:
            print(f"  执行单击: ({cx}, {cy})")
            pyautogui.click(cx, cy)
            time.sleep(wait_after)
            print(f"  单击完成，等待 {wait_after}s")
        elif action == "回车":
            print(f"  执行回车")
            pyautogui.press('enter')
            time.sleep(wait_after)
            print(f"  回车完成，等待 {wait_after}s")
        elif action and cx is None:
            print(f"  [跳过] 无坐标，无法执行动作: {action}")

        # 4.3 如果文本输入不为空，输入文本（通过剪贴板粘贴支持中文）
        if text_input:
            print(f"  输入文本: {text_input}")
            pyperclip.copy(text_input)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.3)
            print(f"  文本输入完成")

        # 4.4 如果滚屏不为0，执行滚屏
        if scroll and scroll != 0:
            direction = "向上" if scroll > 0 else "向下"
            print(f"  执行滚屏: {direction} {abs(scroll)} 个半屏")
            scroll_screen(scroll, hwnd)
            time.sleep(0.5)
            print(f"  滚屏完成")

        # 4.5 如果截屏标志为1，截屏覆盖进程名.png
        if screenshot_flag == "1":
            print(f"  截屏标志为1，正在截屏覆盖: {screenshot_path}")
            capture_and_save(hwnd, screenshot_path)
            print(f"  截屏已更新")

    print("\n" + "=" * 50)
    print("工作流执行完成！")
    return success


def main():
    parser = argparse.ArgumentParser(description="自动化工作流执行器")
    parser.add_argument("--config", default=DEFAULT_WF,
                        help="工作流配置文件路径（默认 wf.json，与 --stdin 二选一）")
    parser.add_argument("--stdin", action="store_true",
                        help="从标准输入读取配置 JSON（与 --config 二选一）")
    args = parser.parse_args()

    if args.stdin:
        # 从 stdin 读取完整配置 JSON
        import sys as _sys
        stdin_text = _sys.stdin.read()
        if not stdin_text.strip():
            print("错误: stdin 为空")
            return
        try:
            config = json.loads(stdin_text)
        except json.JSONDecodeError as e:
            print(f"错误: stdin 不是合法 JSON: {e}")
            return
        print(f"从 stdin 读取配置（{len(stdin_text)} 字符）")
    else:
        config_path = args.config
        if not os.path.isabs(config_path):
            config_path = os.path.join(SCRIPT_DIR, config_path)
        if not os.path.exists(config_path):
            print(f"配置文件不存在: {config_path}")
            return
        print(f"读取配置: {config_path}")
        config = load_config(config_path)

    result = execute_workflow(config)
    # 返回退出码供调用方（如 task_engine）判断成功/失败
    if result:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()

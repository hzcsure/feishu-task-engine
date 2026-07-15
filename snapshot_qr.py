"""
截取 YouTube 视频帧并识别二维码，结果增量写入文件。
支持循环模式：随机启动延迟 + 周期性执行 + 失败累计退出。

流程:
  1. yt-dlp --dump-json 获取视频流 URL（通过 --proxy 支持 SOCKS5）
  2. ffmpeg -http_proxy 直接从流 URL 截取一帧
  3. OpenCV QRCodeDetector 扫描二维码
  4. 解析结果增量写入 url.txt（去重 + 自动淘汰最旧行）

用法:
  python snapshot_qr.py                     # 循环关闭时执行一次，开启时进入循环
  python snapshot_qr.py --image shot.png     # 直接分析已有图片
"""
import sys
import os
import json
import time
import random
import argparse
import subprocess
from datetime import datetime
from pathlib import Path

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    print("警告: opencv-python 未安装，无法识别二维码。pip install opencv-python")

SCRIPT_DIR = Path(__file__).resolve().parent


def load_config():
    """从 sn.json 读取全部配置"""
    cfg = {
        # 工具路径
        "ytdlp": "yt-dlp",
        "ffmpeg": "ffmpeg",
        "node": "",
        # yt-dlp SOCKS5 代理
        "socks5_proxy": "",
        "proxy_enabled": False,
        # ffmpeg HTTP 代理
        "ffmpeg_proxy": "",
        "ffmpeg_proxy_enabled": False,
        # 认证
        "cookies": "",
        # 目标 URL
        "target_url": "https://www.youtube.com/watch?v=FS7IPxmfEms",
        # 二维码输出
        "qr_output_dir": "二维码解析",
        "qr_max_lines": 30,
        # 循环
        "loop_enabled": False,
        "loop_interval": 600,
        "loop_jitter_min": 20,
        "loop_jitter_max": 30,
        "loop_max_failures": 10,
    }
    config_path = SCRIPT_DIR / "sn.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

        # --- yt-dlp SOCKS5 代理 ---
        prx = data.get("代理", {})
        if prx.get("启用", False):
            addr = prx.get("地址", "")
            port = prx.get("端口", 0)
            if addr and port:
                cfg["socks5_proxy"] = f"socks5://{addr}:{port}"
                cfg["proxy_enabled"] = True

        # --- ffmpeg HTTP 代理 ---
        ffprx = data.get("ffmpeg代理", {})
        if ffprx.get("启用", False):
            addr = ffprx.get("地址", "")
            port = ffprx.get("端口", 0)
            if addr and port:
                cfg["ffmpeg_proxy"] = f"http://{addr}:{port}"
                cfg["ffmpeg_proxy_enabled"] = True

        # --- 工具路径 ---
        tools = data.get("工具路径", {})
        if tools.get("ffmpeg"):
            cfg["ffmpeg"] = tools["ffmpeg"]
        if tools.get("node"):
            cfg["node"] = tools["node"]
        for k in ("yt-dlp", "ytdlp"):
            if tools.get(k):
                cfg["ytdlp"] = tools[k]
                break

        # --- 认证 ---
        auth = data.get("认证", {})
        cf = auth.get("cookies文件", "")
        if cf:
            p = Path(cf)
            if not p.is_absolute():
                p = SCRIPT_DIR / p
            if p.exists():
                cfg["cookies"] = str(p)

        # --- 目标 URL ---
        url = data.get("目标URL", "")
        if url:
            cfg["target_url"] = url

        # --- 二维码输出 ---
        qr = data.get("二维码解析", {})
        od = qr.get("输出目录", "")
        if od:
            cfg["qr_output_dir"] = od
        ml = qr.get("最大行数", 30)
        if isinstance(ml, int) and ml > 0:
            cfg["qr_max_lines"] = ml

        # --- 循环 ---
        loop = data.get("循环", {})
        cfg["loop_enabled"] = loop.get("启用", False)
        iv = loop.get("间隔秒", 600)
        if isinstance(iv, (int, float)) and iv > 0:
            cfg["loop_interval"] = int(iv)
        dmin = loop.get("启动延迟最小秒", 20)
        dmax = loop.get("启动延迟最大秒", 30)
        if isinstance(dmin, (int, float)) and dmin >= 0:
            cfg["loop_jitter_min"] = int(dmin)
        if isinstance(dmax, (int, float)) and dmax > 0:
            cfg["loop_jitter_max"] = int(dmax)
        mf = loop.get("最大失败次数", 10)
        if isinstance(mf, int) and mf > 0:
            cfg["loop_max_failures"] = mf

    return cfg


def _clean_env():
    """清除所有代理环境变量，确保直连"""
    env = os.environ.copy()
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
               "ALL_PROXY", "all_proxy"):
        env.pop(k, None)
    return env


def log(msg: str):
    """带时间戳的日志输出"""
    t = datetime.now().strftime("%H:%M:%S")
    print(f"[{t}] {msg}")


def get_stream_url(cfg: dict, video_url: str) -> str:
    """用 yt-dlp 获取视频的直接流 URL"""
    cmd = [
        cfg["ytdlp"],
        "--no-playlist",
        "--socket-timeout", "30",
        "--dump-json",
    ]
    if cfg.get("node"):
        cmd += ["--js-runtimes", f"node:{cfg['node']}"]
    cmd += ["--remote-components", "ejs:github"]

    if cfg.get("proxy_enabled") and cfg.get("socks5_proxy"):
        cmd += ["--proxy", cfg["socks5_proxy"]]
        log(f"  yt-dlp 代理: {cfg['socks5_proxy']}")

    if cfg.get("cookies"):
        cmd += ["--cookies", cfg["cookies"]]

    cmd.append(video_url)
    env = _clean_env()

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                              encoding="utf-8", errors="replace", env=env)
    except subprocess.TimeoutExpired:
        log("  yt-dlp 超时（60秒）")
        return None

    if proc.returncode != 0:
        log(f"  yt-dlp 获取流地址失败 (返回码 {proc.returncode})")
        for line in (proc.stderr or "").strip().split("\n")[-5:]:
            if line.strip():
                log(f"    {line.strip()[:150]}")
        return None

    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log("  yt-dlp 输出异常，无法解析 JSON")
        return None

    stream_url = info.get("url")
    if not stream_url:
        log("  未找到流地址")
        return None

    is_live = info.get("is_live", False)
    title = info.get("title", "")[:60]
    log(f"  视频: {title}")
    log(f"  直播: {'是' if is_live else '否'}")
    return stream_url


def capture_frame(cfg: dict, stream_url: str, output_path: Path) -> bool:
    """用 ffmpeg 从流 URL 直接截取一帧"""
    ffmpeg = cfg["ffmpeg"]
    cmd = [ffmpeg, "-y", "-stats"]

    if cfg.get("ffmpeg_proxy_enabled") and cfg.get("ffmpeg_proxy"):
        cmd += ["-http_proxy", cfg["ffmpeg_proxy"]]
        log(f"  ffmpeg 代理: {cfg['ffmpeg_proxy']}")
    elif cfg.get("proxy_enabled") and cfg.get("socks5_proxy"):
        http_proxy = cfg["socks5_proxy"].replace("socks5://", "http://")
        cmd += ["-http_proxy", http_proxy]
        log(f"  ffmpeg 代理（兼容）: {http_proxy}")

    cmd += ["-i", stream_url,
            "-vframes", "1",
            "-q:v", "2",
            "-update", "1",
            str(output_path)]

    env = _clean_env()

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30,
                              encoding="utf-8", errors="replace", env=env)
        if proc.returncode == 0 and output_path.exists():
            log(f"  帧已提取 ({output_path.stat().st_size/1024:.0f} KB)")
            return True
        for line in (proc.stderr or "").split("\n")[-5:]:
            if line.strip():
                log(f"  {line.strip()[:150]}")
        return False
    except subprocess.TimeoutExpired:
        if output_path.exists() and output_path.stat().st_size > 0:
            log("  帧已提取（超时，文件有效）")
            return True
        log("  ffmpeg 超时（30秒）")
        return False
    except Exception as e:
        log(f"  ffmpeg 异常: {e}")
        return False


def decode_qrcodes(image_path: str) -> list:
    """扫描图片中的二维码，返回 [{"data": ..., "method": ...}, ...]"""
    if not HAS_CV2:
        return []
    img = cv2.imread(image_path)
    if img is None:
        return []
    detector = cv2.QRCodeDetector()
    results = []
    data, _, _ = detector.detectAndDecode(img)
    if data:
        results.append({"data": data.strip(), "method": "direct"})
    if not results:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 51, 2)
        data, _, _ = detector.detectAndDecode(thresh)
        if data:
            results.append({"data": data.strip(), "method": "enhanced"})
    return results


def append_qr_result(cfg: dict, text: str):
    """将二维码解析结果增量写入 url.txt"""
    out_dir = SCRIPT_DIR / cfg.get("qr_output_dir", "二维码解析")
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / "url.txt"
    max_lines = cfg.get("qr_max_lines", 30)

    text = text.strip()
    if not text:
        return

    existing_lines = []
    if file_path.exists():
        raw = file_path.read_text(encoding="utf-8").strip()
        if raw:
            existing_lines = raw.split("\n")

    if text in existing_lines:
        log(f"  二维码结果已存在，跳过写入: {text[:60]}")
        return

    if len(existing_lines) >= max_lines:
        delete_count = len(existing_lines) - max_lines + 1
        existing_lines = existing_lines[delete_count:]

    existing_lines.append(text)
    file_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
    log(f"  二维码结果已写入: {text[:80]}")


def run_once(cfg: dict, frame_path: Path) -> bool:
    """执行单次全流程。成功返回 True，失败返回 False。"""
    target_url = cfg.get("target_url", "")
    if not target_url:
        log("错误: sn.json 中未配置 目标URL")
        return False

    log(f"目标 URL: {target_url}")

    log("第一步: 获取视频流地址")
    stream_url = get_stream_url(cfg, target_url)
    if not stream_url:
        return False

    log("第二步: 直接从流截取视频帧")
    ok = capture_frame(cfg, stream_url, frame_path)
    if not ok:
        return False

    log("第三步: 二维码识别")
    results = decode_qrcodes(str(frame_path))
    log(f"扫码结果: {len(results)} 个二维码")
    for r in results:
        log(f"  [{r['method']}] {r['data']}")

    log("第四步: 写入二维码结果")
    for r in results:
        append_qr_result(cfg, r["data"])

    return True


def run_loop(cfg: dict, frame_path: Path):
    """循环模式：首次立即执行，后续周期性执行 + 失败累计退出"""
    log(f"循环模式启动，间隔 {cfg['loop_interval']} 秒")
    log(f"最大连续失败次数: {cfg['loop_max_failures']}")

    fail_count = 0
    cycle = 0

    while True:
        cycle += 1

        # 第一次立即执行，后续每次执行前先等间隔 + 随机抖动
        if cycle > 1:
            jitter = random.randint(cfg["loop_jitter_min"], cfg["loop_jitter_max"])
            wait = cfg["loop_interval"] + jitter
            log(f"等待 {cfg['loop_interval']}+{jitter}={wait} 秒后进入下一周期...")
            try:
                time.sleep(wait)
            except KeyboardInterrupt:
                log("用户中断，退出")
                break

        log(f"\n{'=' * 40} 第 {cycle} 次执行 {'=' * 40}")

        try:
            success = run_once(cfg, frame_path)
        except KeyboardInterrupt:
            log("用户中断，退出")
            break
        except Exception as e:
            log(f"未预期异常: {e}")
            success = False

        if success:
            fail_count = 0
            log("本周期执行成功")
        else:
            fail_count += 1
            log(f"本周期执行失败（累计失败 {fail_count}/{cfg['loop_max_failures']}）")
            if fail_count >= cfg["loop_max_failures"]:
                log(f"连续失败达到上限 {cfg['loop_max_failures']}，程序退出")
                sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="YouTube 视频帧截图 + 二维码识别")
    parser.add_argument("--image", default="", help="直接分析已有图片，跳过下载")
    args = parser.parse_args()

    cfg = load_config()

    # 帧输出目录
    out_dir = SCRIPT_DIR / cfg.get("qr_output_dir", "二维码解析")
    out_dir.mkdir(parents=True, exist_ok=True)
    frame_path = out_dir / "frame.png"

    # --image 模式：仅分析已有图片，不进循环
    if args.image:
        img_path = args.image
        if not Path(img_path).exists():
            print(f"图片不存在: {img_path}")
            sys.exit(1)
        print(f"分析图片: {img_path}")
        results = decode_qrcodes(img_path)
        print(f"\n扫码结果: {len(results)} 个二维码")
        for r in results:
            print(f"  [{r['method']}] {r['data']}")
        for r in results:
            append_qr_result(cfg, r["data"])
        return

    # 循环 / 单次
    if cfg.get("loop_enabled"):
        run_loop(cfg, frame_path)
    else:
        ok = run_once(cfg, frame_path)
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()

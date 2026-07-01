"""
yt_download.py - YouTube 视频下载器（配置驱动 + 断点续传 + 信息文件）

用法:
  下载单个视频:    python yt_download.py "https://www.youtube.com/watch?v=XXXXX"
  下载多个视频:    python yt_download.py url1 url2 url3
  从文件读取URL:   python yt_download.py -f urls.txt
  查看视频信息:    python yt_download.py --info "URL"
  列出可用格式:    python yt_download.py --formats "URL"
  指定配置文件:    python yt_download.py -c my_config.json "URL"
  不使用代理:      python yt_download.py --no-proxy "URL"
  强制重新下载:    python yt_download.py --force "URL"
"""

import os
import sys
import re
import json
import time
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# ============ 默认配置 ============
SCRIPT_DIR = Path(__file__).parent
DEFAULT_CONFIG = SCRIPT_DIR / "yt_config.json"
# ================================


def sanitize_filename(name):
    """清理文件名：空格→下划线，只保留数字/字母/下划线，合并连续下划线"""
    if not name:
        return "unknown"
    # 空格(含所有空白)替换为下划线
    name = re.sub(r"\s", "_", name)
    # 只保留 a-zA-Z0-9_
    name = re.sub(r"[^a-zA-Z0-9_]", "", name)
    # 合并连续下划线
    name = re.sub(r"_+", "_", name)
    # 去掉首尾下划线
    name = name.strip("_")
    return name or "unknown"


def load_config(config_path):
    """加载配置文件"""
    if not config_path.exists():
        print(f"错误: 配置文件不存在: {config_path}")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_proxy_arg(config):
    """根据配置构建代理参数，返回列表形式供subprocess使用"""
    proxy = config.get("代理", {})
    if not proxy.get("启用", False):
        return []
    protocol = proxy.get("协议", "socks5")
    addr = proxy.get("地址", "127.0.0.1")
    port = proxy.get("端口", 1080)
    proxy_url = f"{protocol}://{addr}:{port}"
    return ["--proxy", proxy_url]


def get_tool_path(config, name, default=None):
    """获取工具路径"""
    paths = config.get("工具路径", {})
    path = paths.get(name, default)
    if path and Path(path).exists():
        return path
    # 尝试 PATH 查找
    return None


def build_base_cmd(config):
    """构建 yt-dlp 基础命令"""
    tools = config.get("工具路径", {})

    # yt-dlp 可执行文件
    ytdlp = tools.get("yt-dlp", "yt-dlp")
    if not Path(ytdlp).exists() and ytdlp != "yt-dlp":
        print(f"警告: yt-dlp 路径不存在: {ytdlp}，尝试使用 PATH 中的 yt-dlp")
        ytdlp = "yt-dlp"

    cmd = [ytdlp]

    # 代理
    cmd += build_proxy_arg(config)

    # cookies
    auth = config.get("认证", {})
    cookies_file = auth.get("cookies文件", "youtube_cookies.txt")
    cookies_path = SCRIPT_DIR / cookies_file if not Path(cookies_file).is_absolute() else Path(cookies_file)
    if cookies_path.exists():
        cmd += ["--cookies", str(cookies_path)]
    else:
        print(f"警告: cookies 文件不存在: {cookies_path}")

    # ffmpeg
    ffmpeg = tools.get("ffmpeg")
    if ffmpeg and Path(ffmpeg).exists():
        cmd += ["--ffmpeg-location", ffmpeg]

    # node.js（用于 n-challenge 签名）
    node = tools.get("node")
    if node and Path(node).exists():
        cmd += ["--js-runtimes", f"node:{node}", "--remote-components", "ejs:github"]

    return cmd


def build_download_cmd(config, url, output_dir, force=False):
    """构建完整下载命令"""
    cmd = build_base_cmd(config)

    dl_cfg = config.get("下载", {})
    resume_cfg = config.get("断点续传", {})

    # 格式选择
    fmt = dl_cfg.get("格式选择", "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best")
    cmd += ["-f", fmt]

    # 合并格式
    merge_fmt = dl_cfg.get("合并格式", "mp4")
    if merge_fmt:
        cmd += ["--merge-output-format", merge_fmt]

    # 输出路径
    template = dl_cfg.get("文件名模板", "%(title)s.%(ext)s")
    output_template = str(Path(output_dir) / template)
    cmd += ["-o", output_template]

    # 文件名清理：空格→下划线，去除非数字字母下划线，合并连续下划线
    cmd += ["--replace-in-metadata", "title", r"\s", "_"]
    cmd += ["--replace-in-metadata", "title", r"[^a-zA-Z0-9_]", ""]
    cmd += ["--replace-in-metadata", "title", r"_+", "_"]

    # 并发下载
    fragments = dl_cfg.get("同时下载片段数", 4)
    if fragments and fragments > 1:
        cmd += ["--concurrent-fragments", str(fragments)]

    # 限速
    rate_limit = dl_cfg.get("限速")
    if rate_limit:
        cmd += ["--limit-rate", str(rate_limit)]

    # 断点续传
    if resume_cfg.get("启用", True) and not force:
        cmd += ["--continue"]  # yt-dlp 默认开启，显式声明
    elif force:
        cmd += ["--no-continue"]  # 强制重新下载

    # 重试
    retries = resume_cfg.get("重试次数", 5)
    cmd += ["--retries", str(retries)]
    retry_sleep = resume_cfg.get("重试间隔秒", 10)
    cmd += ["--retry-sleep", str(retry_sleep)]

    # 字幕
    sub_cfg = config.get("字幕", {})
    if sub_cfg.get("启用", False):
        langs = sub_cfg.get("语言", ["en"])
        for lang in langs:
            cmd += ["--write-subs", "--sub-langs", lang]
        if sub_cfg.get("自动生成", True):
            cmd += ["--write-auto-subs"]
        if sub_cfg.get("嵌入视频", True):
            cmd += ["--embed-subs"]

    # 进度条
    cmd += ["--newline", "--progress"]

    # 视频 URL
    cmd.append(url)

    return cmd


def get_video_info(config, url):
    """获取视频元数据（不下载）"""
    cmd = build_base_cmd(config)
    cmd += ["--dump-json", "--no-playlist", url]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        stdout, _ = proc.communicate(timeout=60)
        if proc.returncode == 0 and stdout:
            text = stdout.decode("utf-8", errors="replace").strip()
            if text:
                return json.loads(text.split("\n")[0])
    except subprocess.TimeoutExpired:
        proc.kill()
        print("获取视频信息超时")
    except Exception as e:
        print(f"获取视频信息失败: {e}")
    return None


def is_already_downloaded(config, url, output_dir):
    """检查视频是否已经下载完成（通过 .downloaded 记录文件）"""
    info = get_video_info(config, url)
    if not info:
        return False, None

    video_id = info.get("id", "")
    title = info.get("title", "unknown")
    ext = "mp4"

    # 检查记录文件
    record_file = Path(output_dir) / f".{video_id}.downloaded"
    if record_file.exists():
        # 记录文件存在，检查实际视频文件是否也在
        expected_name = f"{title}.{ext}"
        for f in Path(output_dir).glob(f"*{video_id}*"):
            if f.suffix in [".mp4", ".mkv", ".webm"]:
                return True, info
        # 记录在但文件不在，可能被移动了
        for f in Path(output_dir).glob("*.mp4"):
            if video_id in str(f) or title in f.stem:
                return True, info

    # 检查 .part 文件（断点续传）
    part_files = list(Path(output_dir).glob(f"*{video_id}*.part"))
    if part_files:
        return False, info  # 有未完成的下载

    # 检查实际视频文件是否已存在（记录文件可能因崩溃未生成）
    safe_title = sanitize_filename(title)
    if safe_title:
        # 优先检查转码后的文件 (z_ 前缀)
        z_mp4 = Path(output_dir) / f"z_{safe_title}.mp4"
        if z_mp4.exists():
            return True, info
        for ext in [".mp4", ".mkv", ".webm"]:
            candidate = Path(output_dir) / f"{safe_title}{ext}"
            if candidate.exists():
                return True, info
        # 模糊匹配
        for ext in [".mp4", ".mkv", ".webm"]:
            matches = list(Path(output_dir).glob(f"*{safe_title[:30]}*{ext}"))
            if matches:
                return True, info

    return False, info


def save_info_file(config, info, video_path, output_dir):
    """下载完成后保存视频信息文本文件"""
    info_cfg = config.get("信息文件", {})
    if not info_cfg.get("启用", True):
        return

    fmt = info_cfg.get("格式", "txt")
    video_id = info.get("id", "unknown")
    title = info.get("title", "unknown")

    # 安全的文件名
    safe_title = sanitize_filename(title)
    info_path = Path(output_dir) / f"{safe_title}_info.{fmt}"

    # 构建信息文本
    lines = []
    lines.append("=" * 60)
    lines.append("YouTube 视频信息")
    lines.append("=" * 60)
    lines.append("")

    field_map = {
        "标题": info.get("title", "N/A"),
        "视频ID": info.get("id", "N/A"),
        "URL": info.get("webpage_url", info.get("original_url", "N/A")),
        "时长": format_duration(info.get("duration", 0)),
        "上传者": info.get("uploader", info.get("channel", "N/A")),
        "上传日期": format_date(info.get("upload_date", "N/A")),
        "观看次数": f"{info.get('view_count', 0):,}" if info.get("view_count") else "N/A",
        "点赞数": f"{info.get('like_count', 0):,}" if info.get("like_count") else "N/A",
        "描述": info.get("description", "N/A"),
        "分辨率": f"{info.get('width', '?')}x{info.get('height', '?')}" if info.get("height") else "N/A",
        "文件大小": format_filesize(video_path.stat().st_size) if video_path.exists() else "N/A",
        "格式": info.get("ext", "mp4"),
        "下载时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    fields = info_cfg.get("包含字段", list(field_map.keys()))
    for field in fields:
        value = field_map.get(field, "N/A")
        lines.append(f"  {field}: {value}")
        lines.append("")

    # 添加可用格式列表
    formats = info.get("formats", [])
    if formats:
        lines.append("-" * 60)
        lines.append("可用格式 (前10个):")
        lines.append("-" * 60)
        for f in formats[-10:]:
            fmt_id = str(f.get("format_id", "?"))
            ext = str(f.get("ext", "?"))
            res = str(f.get("resolution", f"{f.get('width', '?')}x{f.get('height', '?')}"))
            fps = f.get("fps", "")
            fps = str(fps) if fps else ""
            vcodec = str(f.get("vcodec", "none"))[:20]
            acodec = str(f.get("acodec", "none"))[:20]
            size = f.get("filesize", 0)
            size_str = format_filesize(size) if size else "?"
            lines.append(f"  {fmt_id:>6s} | {ext:>5s} | {res:>12s} | {fps:>3s}fps | V:{vcodec:<20s} | A:{acodec:<10s} | {size_str}")

    lines.append("")
    lines.append("=" * 60)

    info_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  信息文件已保存: {info_path.name}")

    # 写入下载记录
    video_id = info.get("id", "")
    if video_id:
        record_file = Path(output_dir) / f".{video_id}.downloaded"
        record_file.write_text(f"{video_path.name}\n{datetime.now().isoformat()}\n", encoding="utf-8")


def format_duration(seconds):
    """格式化时长"""
    if not seconds:
        return "N/A"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_date(date_str):
    """格式化日期 YYYYMMDD -> YYYY-MM-DD"""
    if not date_str or date_str == "N/A":
        return "N/A"
    if len(date_str) == 8:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
    return date_str


def format_filesize(size):
    """格式化文件大小"""
    if not size:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def find_downloaded_video(output_dir, info):
    """在输出目录中查找已下载的视频文件"""
    video_id = info.get("id", "")
    title = info.get("title", "")
    safe_title = sanitize_filename(title)

    # 优先查找转码后的文件 (z_ 前缀)
    if safe_title:
        z_mp4 = Path(output_dir) / f"z_{safe_title}.mp4"
        if z_mp4.exists():
            return z_mp4

    # 尝试用 video_id 匹配
    if video_id:
        for ext in [".mp4", ".mkv", ".webm"]:
            pattern = f"*{video_id}*{ext}"
            matches = list(Path(output_dir).glob(pattern))
            if matches:
                return matches[0]

    # 尝试用标题匹配
    safe_title = sanitize_filename(title)
    if safe_title:
        for ext in [".mp4", ".mkv", ".webm"]:
            pattern = f"{safe_title}{ext}"
            candidate = Path(output_dir) / pattern
            if candidate.exists():
                return candidate
            # 模糊匹配
            matches = list(Path(output_dir).glob(f"*{safe_title[:30]}*{ext}"))
            if matches:
                return matches[0]

    # 找最新的 mp4
    mp4s = sorted(Path(output_dir).glob("*.mp4"), key=lambda f: f.stat().st_mtime, reverse=True)
    if mp4s:
        return mp4s[0]

    return None


def get_ffmpeg_path(config):
    """获取ffmpeg可执行文件路径"""
    ffmpeg = config.get("工具路径", {}).get("ffmpeg", "ffmpeg")
    if ffmpeg and Path(ffmpeg).exists():
        return ffmpeg
    return "ffmpeg"


def extract_audio(config, video_path, output_dir):
    """从视频中提取音频文件（优先流拷贝，失败则重编码）"""
    post = config.get("后处理", {})
    if not post.get("保留音频", False):
        return None

    if not video_path or not video_path.exists():
        return None

    audio_fmt = post.get("音频格式", "m4a")
    safe_title = sanitize_filename(video_path.stem)
    audio_path = Path(output_dir) / f"{safe_title}.{audio_fmt}"

    # 已存在则跳过
    if audio_path.exists():
        print(f"  音频文件已存在: {audio_path.name}")
        return audio_path

    ffmpeg = get_ffmpeg_path(config)

    # 先尝试流拷贝（无损、快速）
    cmd = [ffmpeg, "-i", str(video_path), "-vn", "-acodec", "copy", "-y", str(audio_path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # 流拷贝失败，重新编码
        cmd = [ffmpeg, "-i", str(video_path), "-vn", "-y", str(audio_path)]
        result = subprocess.run(cmd, capture_output=True)

    if audio_path.exists() and audio_path.stat().st_size > 0:
        size = format_filesize(audio_path.stat().st_size)
        print(f"  音频文件已保存: {audio_path.name} ({size})")
        return audio_path
    else:
        print(f"  警告: 音频提取失败")
        if audio_path.exists():
            audio_path.unlink()
        return None


def transcode_to_mp4(config, video_path, output_dir):
    """将webm视频转码为mp4，转码后文件名加前缀"""
    if not video_path or not video_path.exists():
        return video_path

    if video_path.suffix.lower() != ".webm":
        return video_path

    post = config.get("后处理", {})
    if not post.get("webm转mp4", True):
        return video_path

    prefix = post.get("转码文件前缀", "z_")
    mp4_path = Path(output_dir) / f"{prefix}{video_path.stem}.mp4"

    # 已存在则跳过
    if mp4_path.exists():
        print(f"  转码文件已存在: {mp4_path.name}")
        return mp4_path

    ffmpeg = get_ffmpeg_path(config)

    print(f"  正在转码: {video_path.name} -> {mp4_path.name}")
    # 先尝试流拷贝（如果编码兼容，速度快）
    cmd = [ffmpeg, "-i", str(video_path), "-c", "copy", "-y", str(mp4_path)]
    result = subprocess.run(cmd, capture_output=True)
    if result.returncode != 0:
        # 流拷贝失败，重新编码为H.264+AAC
        print(f"  流拷贝失败，重新编码 (H.264+AAC)...")
        cmd = [ffmpeg, "-i", str(video_path), "-c:v", "libx264", "-c:a", "aac", "-y", str(mp4_path)]
        result = subprocess.run(cmd, capture_output=True)

    if mp4_path.exists() and mp4_path.stat().st_size > 0:
        size = format_filesize(mp4_path.stat().st_size)
        print(f"  转码完成: {mp4_path.name} ({size})")
        return mp4_path
    else:
        print(f"  警告: 转码失败，保留原始webm文件")
        if mp4_path.exists():
            mp4_path.unlink()
        return video_path


def download_video(config, url, output_dir, force=False):
    """下载单个视频"""
    print(f"\n{'=' * 60}")
    print(f"URL: {url}")
    print(f"{'=' * 60}")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 检查是否已下载
    if not force:
        print("正在检查下载状态...")
        already_done, info = is_already_downloaded(config, url, output_dir)
        if already_done:
            title = info.get("title", "unknown") if info else "unknown"
            print(f"已下载完成，跳过: {title}")

            # 补充信息文件（如果不存在）
            if info and config.get("信息文件", {}).get("启用", True):
                video_path = find_downloaded_video(output_dir, info)
                if video_path:
                    safe_title = sanitize_filename(info.get("title", ""))
                    info_file = output_dir / f"{safe_title}_info.txt"
                    if not info_file.exists():
                        save_info_file(config, info, video_path, output_dir)
                    print(f"VIDEO_FILE: {video_path.name}")
                else:
                    print("  警告: 找不到视频文件，可能已被移动")
            return True

        # 检查是否有 .part 文件（断点续传）
        if info:
            video_id = info.get("id", "")
            part_files = list(output_dir.glob(f"*{video_id}*.part"))
            if part_files:
                print(f"发现 {len(part_files)} 个未完成片段，将断点续传...")
    else:
        info = get_video_info(config, url)
        print("强制重新下载模式")

    if info:
        title = info.get("title", "N/A")
        duration = format_duration(info.get("duration", 0))
        uploader = info.get("uploader", "N/A")
        print(f"标题: {title}")
        print(f"时长: {duration}")
        print(f"上传者: {uploader}")

    # 构建下载命令
    cmd = build_download_cmd(config, url, output_dir, force=force)

    # 执行下载
    print(f"\n开始下载...")
    print(f"命令: {' '.join(cmd[:6])}... {url}")
    print("-" * 60)

    try:
        result = subprocess.run(cmd)
        success = result.returncode == 0
    except KeyboardInterrupt:
        print("\n用户中断下载，已保存断点，可重新运行续传")
        return False
    except Exception as e:
        print(f"下载出错: {e}")
        return False

    if success:
        print(f"\n下载完成!")
        # 后处理
        if info:
            video_path = find_downloaded_video(output_dir, info)
            if video_path and video_path.exists():
                # webm 转 mp4
                video_path = transcode_to_mp4(config, video_path, output_dir)
                # 提取音频
                extract_audio(config, video_path, output_dir)
                size = format_filesize(video_path.stat().st_size)
                print(f"视频文件: {video_path.name} ({size})")
                print(f"VIDEO_FILE: {video_path.name}")
                save_info_file(config, info, video_path, output_dir)
            else:
                print("警告: 未找到下载的视频文件")
                # 尝试重新获取信息
                fresh_info = get_video_info(config, url)
                if fresh_info:
                    video_path = find_downloaded_video(output_dir, fresh_info)
                    if video_path and video_path.exists():
                        video_path = transcode_to_mp4(config, video_path, output_dir)
                        extract_audio(config, video_path, output_dir)
                        save_info_file(config, fresh_info, video_path, output_dir)
                        print(f"VIDEO_FILE: {video_path.name}")
        return True
    else:
        print(f"\n下载失败 (返回码: {result.returncode})")
        resume_cfg = config.get("断点续传", {})
        if resume_cfg.get("启用", True):
            print("断点续传已启用，可重新运行此命令继续下载")
        return False


def show_formats(config, url):
    """列出视频可用格式"""
    print(f"正在获取格式列表: {url}")
    cmd = build_base_cmd(config)
    cmd += ["--list-formats", "--no-playlist", url]
    subprocess.run(cmd)


def show_info(config, url):
    """显示视频信息（不下载）"""
    print(f"正在获取视频信息: {url}\n")
    info = get_video_info(config, url)
    if not info:
        print("获取失败")
        return

    print(f"  标题:     {info.get('title', 'N/A')}")
    print(f"  视频ID:   {info.get('id', 'N/A')}")
    print(f"  URL:      {info.get('webpage_url', url)}")
    print(f"  时长:     {format_duration(info.get('duration', 0))}")
    print(f"  上传者:   {info.get('uploader', 'N/A')}")
    print(f"  上传日期: {format_date(info.get('upload_date', 'N/A'))}")
    print(f"  观看次数: {info.get('view_count', 0):,}" if info.get('view_count') else "  观看次数: N/A")
    print(f"  点赞数:   {info.get('like_count', 0):,}" if info.get('like_count') else "  点赞数: N/A")
    desc = info.get("description", "")
    if desc:
        print(f"\n  描述 (前200字):")
        print(f"  {desc[:200]}...")


def main():
    parser = argparse.ArgumentParser(
        description="YouTube 视频下载器（配置驱动 + 断点续传）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python yt_download.py "https://www.youtube.com/watch?v=XXXXX"
  python yt_download.py -f urls.txt
  python yt_download.py --info "URL"
  python yt_download.py --formats "URL"
  python yt_download.py --no-proxy --force "URL"
        """
    )
    parser.add_argument("urls", nargs="*", help="视频URL（可多个）")
    parser.add_argument("-f", "--file", help="从文本文件读取URL（每行一个）")
    parser.add_argument("-c", "--config", default=str(DEFAULT_CONFIG), help="配置文件路径")
    parser.add_argument("--no-proxy", action="store_true", help="本次不使用代理")
    parser.add_argument("--force", action="store_true", help="强制重新下载（忽略断点续传）")
    parser.add_argument("--info", action="store_true", help="仅显示视频信息，不下载")
    parser.add_argument("--formats", action="store_true", help="列出可用格式，不下载")
    args = parser.parse_args()

    # 加载配置
    config = load_config(Path(args.config))

    # --no-proxy 临时关闭代理
    if args.no_proxy:
        config["代理"]["启用"] = False
        print("已临时关闭代理")

    # 收集URL
    urls = list(args.urls)
    if args.file:
        file_path = Path(args.file)
        if file_path.exists():
            for line in file_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
        else:
            print(f"错误: URL文件不存在: {file_path}")
            sys.exit(1)

    if not urls:
        parser.print_help()
        sys.exit(0)

    # 仅显示信息
    if args.info:
        for url in urls:
            show_info(config, url)
            print()
        return

    # 仅列出格式
    if args.formats:
        for url in urls:
            show_formats(config, url)
        return

    # 输出目录
    dl_cfg = config.get("下载", {})
    output_dir = dl_cfg.get("输出目录", "downloads")
    if not Path(output_dir).is_absolute():
        output_dir = SCRIPT_DIR / output_dir

    # 下载
    success_count = 0
    fail_count = 0
    for i, url in enumerate(urls, 1):
        print(f"\n[{i}/{len(urls)}] 处理中...")
        if download_video(config, url, output_dir, force=args.force):
            success_count += 1
        else:
            fail_count += 1

    # 汇总
    print(f"\n{'=' * 60}")
    print(f"下载完成: 成功 {success_count} 个, 失败 {fail_count} 个")
    print(f"输出目录: {output_dir}")
    print(f"{'=' * 60}")

    # 有失败时返回非零退出码，告知调用方
    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()

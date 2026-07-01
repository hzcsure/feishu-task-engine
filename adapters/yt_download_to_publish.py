"""
适配器: yt_download_to_publish

后处理适配器（绑定下载阶段），在下载完成后执行：
1. 从 stdout 查找已下载的视频文件路径
2. 从 info.txt 提取视频元数据（标题、描述）
3. 从表单字段获取标题和标签
4. 组装最终描述（含 #标签）
5. 渲染发布工作流模板 → 写入 context["publish_config"]

用于 task_configs.json:
  "后处理适配器": "yt_download_to_publish"
"""
import os
import re
import json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
PUBLISH_DIR = SCRIPT_DIR / "WeChatAppEx"
DOWNLOADS_DIR = SCRIPT_DIR / "downloads"
PUBLISH_HISTORY = SCRIPT_DIR / ".publish_history.json"

DEFAULT_TITLE_MAX_LEN = 30
DEFAULT_DESC_MAX_LEN = 200


# ── 工具函数（从原 prepare_for_publish.py 迁移） ──

def _load_publish_history():
    if PUBLISH_HISTORY.exists():
        with open(PUBLISH_HISTORY, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"published_urls": []}


def _save_publish_history(history):
    with open(PUBLISH_HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def _is_already_published(video_url):
    if not video_url:
        return False
    history = _load_publish_history()
    return video_url in history.get("published_urls", [])


def _mark_as_published(video_url):
    if not video_url:
        return
    history = _load_publish_history()
    if video_url not in history.get("published_urls", []):
        history.setdefault("published_urls", []).append(video_url)
        _save_publish_history(history)


def _truncate(text, max_len):
    if not text:
        return ""
    if len(text) > max_len:
        return text[:max_len - 3] + "..."
    return text


def _build_description(raw_description, tags_str):
    """组装发布用描述：标签行 + 换行 + 描述，总长不超过900字符"""
    parts = []
    # 1. 标签行在前
    if tags_str:
        tag_list = [t.strip().lstrip("#") for t in tags_str.split(",") if t.strip()]
        if tag_list:
            tag_line = " ".join(f"#{t}" for t in tag_list)
            parts.append(tag_line)
    # 2. 描述在后
    first_para = (raw_description or "").strip().split("\n")[0]
    if first_para:
        parts.append(first_para)
    # 3. 拼接，超900截断
    result = "\n".join(parts)
    if len(result) > 900:
        result = result[:900]
    return result


def _find_latest_download():
    """查找 downloads/ 下最新的 mp4 及对应的 info 文件"""
    if not DOWNLOADS_DIR.exists():
        return None, None
    mp4_files = sorted(DOWNLOADS_DIR.glob("*.mp4"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
    if not mp4_files:
        return None, None
    latest = mp4_files[0]
    stem = latest.stem
    if stem.startswith("z_"):
        stem = stem[2:]
    # 找 info 文件
    info_files = list(DOWNLOADS_DIR.glob(f"{stem}_info.txt"))
    if not info_files:
        info_files = sorted(DOWNLOADS_DIR.glob("*_info.txt"),
                            key=lambda f: f.stat().st_mtime, reverse=True)
    return latest, info_files[0] if info_files else None


def _parse_info_file(info_path):
    """从 info.txt 解析元数据"""
    metadata = {"title": "", "description": "", "video_url": ""}
    if not info_path or not info_path.exists():
        return metadata
    content = info_path.read_text(encoding="utf-8")
    m = re.search(r"标题:[ \t]*(.+)", content)
    if m:
        metadata["title"] = m.group(1).strip()
    m = re.search(r"描述:[ \t]*(.+)", content)
    if m:
        metadata["description"] = m.group(1).strip()
    m = re.search(r"URL:[ \t]*(.+)", content)
    if m:
        metadata["video_url"] = m.group(1).strip()
    return metadata


def _render_template_string(template_path, values):
    """读取模板文件，替换 {{变量}}，返回渲染后的字符串"""
    content = template_path.read_text(encoding="utf-8")
    for key, val in values.items():
        escaped = json.dumps(val, ensure_ascii=False)[1:-1]
        content = content.replace("{{" + key + "}}", escaped)
    return content


# ── 适配器接口 ──

def prepare_input(context):
    """下载阶段无前置准备，直接返回"""
    return context


def process_output(stdout, context):
    """
    下载阶段的后处理适配：解析 VIDEO_FILE 输出，将文件名存入 context
    供发布阶段（publish_prepare）直接使用，避免按修改时间查找文件。
    """
    if not stdout:
        return context

    for line in stdout.split("\n"):
        line = line.strip()
        if line.startswith("VIDEO_FILE:"):
            video_filename = line.split(":", 1)[1].strip()
            if video_filename:
                context["video_filename"] = video_filename
                # 提取 stem（去扩展名、去 z_ 前缀）
                stem = video_filename.rsplit(".", 1)[0]
                if stem.startswith("z_"):
                    stem = stem[2:]
                context["video_stem"] = stem
                print(f"  [适配] 捕获到视频文件名: {video_filename}", flush=True)
                break

    return context

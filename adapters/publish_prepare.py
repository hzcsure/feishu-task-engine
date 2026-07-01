"""
适配器: publish_prepare

输入准备适配器（绑定发布阶段），在发布阶段执行前完成所有准备工作：
1. 查找已下载的视频文件和信息文件
2. 提取元数据（标题、描述）
3. 组装描述（含 #标签）
4. 复制视频到发布目录（保留原始文件名）
5. 渲染发布工作流模板
6. 将配置写入 stdin_data，供 run_workflow.py --stdin 读取
7. 后处理：标记已发布，清理临时数据

用于 task_configs.json:
  "输入准备适配器": "publish_prepare"

依赖: adapters/yt_download_to_publish.py 中的工具函数
"""
import json
import re
import shutil
from pathlib import Path

from adapters.yt_download_to_publish import (
    _find_latest_download,
    _parse_info_file,
    _build_description,
    _truncate,
    _render_template_string,
    _is_already_published,
    _mark_as_published,
    SCRIPT_DIR,
    PUBLISH_DIR,
    DOWNLOADS_DIR,
    DEFAULT_TITLE_MAX_LEN,
    DEFAULT_DESC_MAX_LEN,
)


# ── 标题清理 ──

# 允许保留的字符集合：字母数字CJK + 书名号、引号、冒号、加号、问号、百分号、摄氏度
_ALLOWED_CHARS = re.compile(
    r"[^a-zA-Z0-9"
    r"\u4e00-\u9fff"              # CJK 统一表意文字（中文）
    r"\u3000-\u303f"              # CJK 符号和标点
    r"\《\》"
    r"\u201c\u201d\u2018\u2019"  # 中文引号 “ ” ‘ ’
    r"\u0022"                    # 英文双引号 "
    r"\u003A\uFF1A"              # 冒号 : ：
    r"\+"
    r"\u003F\uFF1F"              # 问号 ? ？
    r"\%"
    r"\u2103"                    # 摄氏度 ℃
    r"]"
)


def _sanitize_title(title):
    """清理标题：只保留字母数字和指定标点，逗号转空格"""
    if not title:
        return title
    # 不允许的字符替换为空格（保留单词间的分隔）
    title = _ALLOWED_CHARS.sub(" ", title)
    # 逗号转空格
    title = title.replace(",", " ").replace("，", " ")
    # 合并连续空格
    title = re.sub(r"\s+", " ", title).strip()
    return title


def prepare_input(context):
    """
    发布阶段的输入准备（整合了下载后处理 + 发布前准备）：
    查找视频 → 提取元数据 → 复制文件 → 渲染模板 → 准备 stdin
    """
    fields = context.get("fields", {})
    video_url = fields.get("video_url", "")
    template_file = SCRIPT_DIR / "wf_publish.template.json"

    # 1. 去重检查
    if _is_already_published(video_url):
        print("  [适配] 视频已发布过，跳过发布", flush=True)
        context["skip_publish"] = True
        return context

    # 2. 查找视频和 info（优先使用 context 中由下载阶段传入的文件名）
    video_path = None
    info_path = None
    video_filename = context.get("video_filename", "")
    if video_filename:
        candidate = DOWNLOADS_DIR / video_filename
        if candidate.exists():
            video_path = candidate
            # 根据 video_filename 找对应的 info 文件
            stem = context.get("video_stem", "")
            if not stem:
                stem = video_filename.rsplit(".", 1)[0]
                if stem.startswith("z_"):
                    stem = stem[2:]
            info_candidates = list(DOWNLOADS_DIR.glob(f"{stem}_info.*"))
            if info_candidates:
                info_path = info_candidates[0]
            print(f"  [适配] 使用上下文中的文件名: {video_filename}", flush=True)

    if not video_path:
        # 回退：按最新修改时间查找
        video_path, info_path = _find_latest_download()
        if video_path:
            print(f"  [适配] 按最新修改时间找到: {video_path.name}", flush=True)

    if not video_path:
        print("  [适配] 未找到已下载的视频文件", flush=True)
        context["skip_publish"] = True
        return context

    # 3. 解析元数据
    metadata = _parse_info_file(info_path) if info_path else {}
    raw_title = metadata.get("title", "")
    raw_desc = metadata.get("description", "")
    orig_video_url = metadata.get("video_url", "") or video_url

    # 4. 清理标题符号 + 组装（最短6字，最长16字，过短循环填充）
    title = fields.get("title", "") or raw_title
    title = _sanitize_title(title)
    if title:
        title = title.strip()
        # 过短循环填充：如 "AB" → "ABAB" → "ABABABAB"
        while len(title) < 6:
            title = title + title
        # 过长截断
        if len(title) > 16:
            title = title[:16]
    else:
        # 完全没有标题，从文件名提取
        title = video_path.stem.replace("z_", "")
        title = _truncate(title, 16)
        while len(title) < 6:
            title = title + title
        if len(title) > 16:
            title = title[:16]

    # 5. 组装描述（含 #标签）
    tags = fields.get("tags", "")
    description = _build_description(raw_desc, tags)
    # 描述为空时，回退使用标题字段
    if not description:
        description = title

    # 6. 复制视频到发布目录（保留原始文件名）
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    publish_video = PUBLISH_DIR / video_path.name
    shutil.copy2(video_path, publish_video)

    # 7. 渲染发布模板
    if not template_file.exists():
        print(f"  [适配] 模板文件不存在: {template_file}", flush=True)
        context["skip_publish"] = True
        return context

    video_dir_abs = str(PUBLISH_DIR.resolve()).replace("\\", "/") + "/"
    values = {
        "video_dir": video_dir_abs,
        "video_file": video_path.name,
        "title": title,
        "description": description,
    }
    publish_config_str = _render_template_string(template_file, values)

    # 8. 写入 context
    context["publish_config"] = publish_config_str
    context["publish_video_path"] = str(publish_video)
    context["publish_title"] = title
    context["publish_description"] = description
    context["publish_video_url"] = orig_video_url
    context["video_filename"] = video_path.name

    # 9. 准备 stdin 数据（添加发布时间）
    try:
        config = json.loads(publish_config_str)
        publish_time = fields.get("publish_time", "")
        if publish_time and publish_time != "立即":
            config["发布时间"] = publish_time
        context["stdin_data"] = json.dumps(config, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        context["stdin_data"] = publish_config_str

    print(f"  [适配] 发布配置已生成（{len(publish_config_str)} 字符）", flush=True)
    return context


def process_output(stdout, context):
    """
    发布阶段的后处理：
    标记已发布，清理临时数据
    """
    video_url = context.get("publish_video_url", "")
    if video_url:
        _mark_as_published(video_url)
        print(f"  [适配] 视频已标记为已发布", flush=True)

    # 清理临时数据
    for key in list(context.keys()):
        if key.startswith("publish_") or key == "stdin_data":
            del context[key]

    return context

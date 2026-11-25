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
import sys
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

# 判定「有效内容字符」：字母、数字、中文。用于识别纯符号标题（清理后仅残留 % 等标点）。
_VALID_CORE = re.compile(r"[a-zA-Z0-9\u4e00-\u9fff]")


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


def _has_valid_core(text):
    """判断清理后的标题是否仍含有效内容（字母/数字/中文）。

    用于规避纯符号标题（如 "!@#$%^" 清理后残留 "%"）被当作有效标题。
    """
    return bool(_VALID_CORE.search(text or ""))


def _extract_subtitle_text(video_path):
    """查找与视频同 stem 的字幕文件（.vtt/.srt），剥离时间戳与格式标签，返回纯文本。

    yt-dlp 字幕命名：<stem>.<lang>.vtt / <stem>.<lang>.srt（stem 可能带 z_ 前缀或
    转码处理）。优先 .srt（结构简单），其次 .vtt。找不到返回空串。
    """
    if not video_path:
        return ""
    stem = video_path.stem
    if stem.startswith("z_"):
        stem = stem[2:]
    candidates = []
    # 精确匹配：文件名必须严格以 "<stem>." 开头（<stem>.<lang>.vtt/srt）。
    # 用 Python 字符串前缀判断，而非 glob 通配符，避免 stem 含 [ ] ? * 等
    # 特殊字符被误解析，也避免误匹配到其他视频（如「猫」≠「小猫」）。
    prefix = stem + "."
    for f in DOWNLOADS_DIR.glob("*.vtt"):
        if f.name.startswith(prefix):
            candidates.append(f)
    for f in DOWNLOADS_DIR.glob("*.srt"):
        if f.name.startswith(prefix):
            candidates.append(f)
    # 去重保序，srt 优先
    seen, ordered = set(), []
    for f in candidates:
        if f.name not in seen:
            seen.add(f.name)
            ordered.append(f)
    ordered.sort(key=lambda f: (f.suffix != ".srt", f.name))
    if not ordered:
        return ""
    sub_path = ordered[0]
    text = sub_path.read_text(encoding="utf-8", errors="replace")
    return _strip_subtitle(text)


def _strip_subtitle(raw):
    """把 .vtt/.srt 内容剥离成纯文本（去 WEBVTT 头、时间轴、序号、格式标签、重复行）。"""
    lines = []
    seen = set()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if re.match(r"^\d+$", line):            # srt 序号
            continue
        if "-->" in line:                        # 时间轴
            continue
        if re.match(r"^NOTE\b", line):           # vtt NOTE 块
            continue
        # 去内联标签 <...> 与时间戳 cue 标记
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{[^}]*\}", "", line)
        if line and line not in seen:            # YouTube ASR 常出现连续重复行
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


def _summarize_info(info_path, subtitle_text=""):
    """调用 util/summarize.py 对视频内容做 AI 摘要（两级退避）。

    优先级：字幕纯文本 > info.txt 元数据；均失败/为空时返回空 dict，
    由调用方走现有正则解析路径。
    """
    try:
        util_dir = Path(__file__).resolve().parent.parent / "util"
        if str(util_dir) not in sys.path:
            sys.path.insert(0, str(util_dir))
        from summarize import summarize_file, summarize_text

        if subtitle_text and subtitle_text.strip():
            fields = summarize_text(subtitle_text, "video_summary")
            source = "字幕"
        elif info_path and Path(info_path).exists():
            fields = summarize_file(str(info_path), "video_summary")
            source = "info"
        else:
            return {}

        overview = (fields.get("overview") or "").strip()
        brief = (fields.get("brief") or "").strip()
        if overview or brief:
            print(f"  [适配] AI 摘要来源: {source}", flush=True)
        return {"overview": overview, "brief": brief}
    except Exception as exc:
        print(f"  [适配] AI 摘要不可用，回退正则解析: {exc}", flush=True)
        return {}


def _build_title(raw_title, video_stem, min_len=6, max_len=16):
    """组装发布标题（替代原先散落在 prepare_input 中的翻倍填充逻辑）。

    关键差异：
    1. 空串/纯符号标题不再进入 `while title = title + title` 翻倍循环（空串会死循环）；
    2. 清理后核心字符为 0 时，回退到文件名 stem，再回退到占位「视频」；
    3. 过短用「重复末字符」确定性填充，单次完成，无死循环可能；
    4. 过长截断（先按字符数安全截断，避免切在代理对中间）。
    """
    title = _sanitize_title(raw_title or "")
    source = "raw"

    # 核心字符为 0 → 视为无效（例如 "!@#$%" 清理后残留 "%"，但无实际内容）
    if not _has_valid_core(title):
        title = ""

    if not title:
        stem_title = _sanitize_title((video_stem or "").replace("z_", ""))
        if _has_valid_core(stem_title):
            title = stem_title
            source = "stem"
        else:
            title = "视频"
            source = "fallback"

    # 过短 → 重复末字符填充（确定性、单次完成，无死循环可能）
    if len(title) < min_len:
        title = title + title[-1] * (min_len - len(title))

    # 过长 → 截断
    if len(title) > max_len:
        title = title[:max_len]

    return title, source


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

    # 3.1 AI 摘要增强（优先）：字幕纯文本 > info.txt；失败静默回退正则解析
    subtitle_text = _extract_subtitle_text(video_path)
    ai = _summarize_info(info_path, subtitle_text)
    ai_overview = ai.get("overview", "")
    ai_brief = ai.get("brief", "")

    # 4. 清理标题符号 + 组装（最短6字，最长16字；确定性填充，无死循环）
    #    brief 优先于正则解析出的 raw_title，但仍过 _build_title 的 6 字最小填充
    title = fields.get("title", "") or ai_brief or raw_title
    title, _src = _build_title(title, video_path.stem)

    # 5. 组装描述（含 #标签）
    #    overview 优先于正则解析出的 raw_desc
    tags = fields.get("tags", "")
    desc_source = ai_overview or raw_desc
    description = _build_description(desc_source, tags)
    # 描述为空时，回退使用标题字段
    if not description:
        description = title

    # 6. 复制视频到发布目录（保留原始文件名）
    PUBLISH_DIR.mkdir(parents=True, exist_ok=True)
    publish_video = PUBLISH_DIR / video_path.name
    try:
        shutil.copy2(video_path, publish_video)
    except OSError as exc:
        print(f"  [适配] 复制视频失败: {exc}，跳过本次发布", flush=True)
        context["skip_publish"] = True
        return context

    # 7. 渲染发布模板
    if not template_file.exists():
        print(f"  [适配] 模板文件不存在: {template_file}", flush=True)
        context["skip_publish"] = True
        return context

    video_dir_abs = str(PUBLISH_DIR.resolve()) + "\\"
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
        try:
            _mark_as_published(video_url)
            print(f"  [适配] 视频已标记为已发布", flush=True)
        except OSError as exc:
            # 历史文件写失败不应阻断后续清理，仅告警
            print(f"  [适配] 标记已发布失败: {exc}", flush=True)

    # 清理临时数据
    for key in list(context.keys()):
        if key.startswith("publish_") or key == "stdin_data":
            del context[key]

    return context

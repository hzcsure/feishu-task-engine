# -*- coding: utf-8 -*-
"""summary_templates.py — 模板声明（纯配置，不含逻辑）

这个文件只放「数据」：模板怎么写、字段怎么约束、风格是什么。
`summarize.py` 负责渲染提示、校验绑定、调用 API、收口长度。
因此：**改文案 / 加模板只动本文件，不需要碰 summarize.py。**

一份模板的键（全部由 summarize.py 消费）：

  version       int    文案版本，随文案递增（缓存键另含指纹，见 _fingerprint）
  description   str    一句话说明，--list-templates 里显示
  params        dict   请求参数：thinking / max_tokens / response_format…
  role          str    模型扮演的角色（渲染到 [ROLE]）
  schema        dict   字段表 name -> {type, min_chars, max_chars,
                                    trim_punct, label}
                       label 只用于打印标题，不进提示词；
                       是否有 max_chars 决定 polished 时怎么收口
  preprocess    list   清洗步骤，按顺序编号渲染到 [PREPROCESS]
  style         str    文体与格式要求（[STYLE]）
  user          str    用户消息模板，**必须含 {{text}}** 占位
  parser        str    终稿解析器名，须在 summarize.py 的 PARSERS 里注册
  map           dict   可选。超长分块时「一块 → 一句要点」的指令：
                       {system, parser, field, max_tokens}
                       省略则用本文件的 DEFAULT_MAP（措辞中性）
  tags          bool   可选，默认 True。是否从原文抽取 hashtag；
                       会议记录这类文体没有标签概念，置 False 即可不打印

新增模板 = 在 TEMPLATES 里加一个 key，其余一律不用改。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 模板
TEMPLATES: dict[str, dict] = {
    # ------------------------------------------------------------ 模板 1
    "video_summary": {
        "version": 6,
        "description": "口播稿 / 视频信息 → 100 字概述 + 16 字小标题（标签另从原文抽取）",
        "params": {
            "thinking": "disabled",
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        },
        "role": "你是摘要器，只输出 JSON，不解释、不加代码块。",
        "schema": {
            "overview": {"type": "string", "min_chars": 50, "max_chars": 100,
                         "label": "概述"},
            "brief": {"type": "string", "max_chars": 16, "trim_punct": True,
                      "label": "简述"},
        },
        "preprocess": [
            "翻译为中文"
            "删除推广、会员、订阅、投稿、联系方式、外链与频道自述",
            "删除时长、分辨率、文件大小、下载时间等元数据",
            "若清洗后无结果，overview 与 brief 均填「无正文」",
        ],
        "style": "简体中文；brief 不加标点；不输出字数统计；不加代码块。",
        "user": "原文：\n{{text}}",
        # map 段：只描述「一块文本 → 一句要点」，与终稿格式无关
        "map": {
            "system": '把这段口播稿压成一句话要点，只输出JSON：{"gist":"..."}',
            "parser": "json_fields",
            "field": "gist",
            "max_tokens": 120,
        },
        "parser": "json_fields",
    },

    # ------------------------------------------------------------ 模板 2
    # 字段名与模板 1 完全不同 —— 输出按各自 schema 渲染，不写死在代码里。
    "meeting_notes": {
        "version": 1,
        "description": "会议记录 → 90 字结论 + 待办 + 14 字标题（不抽标签）",
        "params": {
            "thinking": "disabled",
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        },
        "role": "你是会议纪要提炼器，只输出 JSON，不解释、不加代码块。",
        "schema": {
            "conclusion": {"type": "string", "min_chars": 40, "max_chars": 90,
                           "label": "结论"},
            "actions": {"type": "string", "max_chars": 80,
                        "label": "待办"},
            "title": {"type": "string", "max_chars": 14, "trim_punct": True,
                      "label": "标题"},
        },
        "preprocess": [
            "删除寒暄、自我介绍、参会名单、日程调整、设备与录音问题",
            "只保留已形成的决议、责任人、时间点与待确认事项",
            "若清洗后无实质内容，所有字段均填「无实质内容」",
        ],
        "style": "简体中文；actions 用「谁 + 做什么 + 何时」的短句，"
                 "多项用「；」分隔；title 不加标点。",
        "user": "会议记录：\n{{text}}",
        "map": {
            "system": '把这段会议记录压成一句要点，只输出JSON：{"gist":"..."}',
            "parser": "json_fields",
            "field": "gist",
            "max_tokens": 120,
        },
        "parser": "json_fields",
        "tags": False,
    },
}

# map 段缺省值：新模板不写 map 也能跑，且不含任何业务措辞
DEFAULT_MAP: dict = {
    "system": '把这段文本压成一句话要点，只输出JSON：{"gist":"..."}',
    "parser": "json_fields",
    "field": "gist",
    "max_tokens": 120,
}

# -t 省略时用哪个模板
#DEFAULT_TEMPLATE = "video_summary"
DEFAULT_TEMPLATE = "video_summary"
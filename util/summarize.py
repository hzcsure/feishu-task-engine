#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""summarize.py — 长文本摘要（DeepSeek 官方 API，OpenAI 兼容格式）

输出由模板决定（默认模板 video_summary）：
  overview  概述（50–100 字）
  brief     小标题（≤16 字）
  tags      #标签（从原文已有 hashtag 抽取，不让模型生成）

三件事的分工（这是本项目的核心结构）：
  模板  summary_templates.py      外部声明模块：角色 / 字段约束 / 清洗步骤 / 风格
  绑定  parser 字段 → PARSERS     启动期校验，拼错立刻报错，不会跑到一半才炸
  调用  chat()                    只管发请求、留档请求体与原生响应、统计 token

设计取向：零依赖（仅标准库）；模板与逻辑分离，本文件不含任何文体措辞，
内置模板不带写死输出格式（按 schema 渲染）。新增模板只改 summary_templates.py。

省 token 的动作：
  1. 关闭思考模式（官方默认开启，摘要任务里推理 token 是纯浪费）
  2. deepseek-flash（同任务约 pro 的 1/4 价格）
  3. 系统提示固定且短 —— 命中上下文缓存（价格 1/50）
  4. json_object —— 免寒暄与 Markdown 包装
  5. max_tokens 400 —— 100 字概述 + 16 字小标题，物理上够用
  6. 超长文本头尾采样，不整篇硬塞
  7. 本地缓存（--cache）—— 同一篇重复摘要 0 token
  8. 标签在客户端抽取 —— 不占提示词、不占输出、不会编造

用法：
  python summarize.py --list-templates             # 看有哪些模板
  python summarize.py -f info.txt
  python summarize.py -f info.txt -t meeting_notes # 换模板
  python summarize.py -f info.txt --stats          # token + 费用
  python summarize.py -f info.txt --json           # 含请求体与原生响应，可重定向留档
  python summarize.py -f info.txt --raw            # 打印原生返回内容供备查
  python summarize.py -f info.txt --req            # 打印请求体：实际发出去的 system/user
  python summarize.py -f info.txt --req --raw      # 请求 + 返回，完整往返
  python summarize.py -f a.txt --cache --audit     # 缓存 + 追加审计日志
  type a.txt | python summarize.py
  python summarize.py -f long.txt --chunk          # 超长：分块摘要再归并

库调用（不经过命令行，见 example_lib.py）：
  from summarize import summarize_file
  summarize_file("info.txt", "video_summary")   # -> {"overview": "...", "brief": "..."}
  run_file("info.txt", "video_summary").meta    # token / 费用 / 原生响应
  失败一律抛 SummarizeError 家族（TemplateError / InputError / ApiError），
  不 print、不 sys.exit —— CLI 才需要退出码。

退出码：0 成功 / 1 参数或配置错误 / 2 调用失败
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

SETTINGS_PATH = pathlib.Path.home() / ".claude" / "settings.json"
CACHE_DIR = pathlib.Path(__file__).parent / ".cache"   # 默认缓存目录（可用 cache_dir 覆盖）

# 给人 import 的公开接口（其余名字都是内部实现）
__all__ = ["summarize_file", "summarize_text", "run_file", "run_text",
           "SummaryResult", "SummarizeError", "TemplateError", "InputError",
           "ApiError", "read_text_file", "TEMPLATES", "PARSERS"]

# ---------------------------------------------------------------- 价格表
# 美元 / 1M token，官方 pricing 页 2026-11 快照；高峰为低峰 2 倍
PRICE = {
    "deepseek-flash": {"hit": 0.003, "miss": 0.15, "out": 0.6},
    "deepseek-v4-pro": {"hit": 0.022, "miss": 0.66, "out": 1.98},
}


# ---------------------------------------------------------------- 异常
# 库调用要的是异常（调用方自己决定怎么处理），CLI 要的是退出码。
# 所以异常自带 exit_code，由 main() 翻译成返回值 —— 库代码里绝不出现 sys.exit。
class SummarizeError(RuntimeError):
    """本模块所有「可预期失败」的基类。"""
    exit_code = 1


class TemplateError(SummarizeError):
    """模板有问题：ID 不存在、schema 为空、parser 未注册、缺 {{text}}。"""


class InputError(SummarizeError):
    """输入有问题：文件不存在、解码失败、正文为空、没有 API Key。"""


class ApiError(SummarizeError):
    """调用失败：HTTP 错误、超时、响应无法解析。"""
    exit_code = 2


# ---------------------------------------------------------------- 模板（外部模块）
# 模板配置全部在 summary_templates.py —— 本文件不写任何文体措辞，也不内置模板。
# 那个模块只允许「声明」；新增模板 = 在它的 TEMPLATES 里加一个 key。
try:
    from summary_templates import DEFAULT_MAP, DEFAULT_TEMPLATE, TEMPLATES
except ImportError as e:                 # 同目录缺失 / 该模块自身有语法错
    raise ImportError(
        f"无法加载 summary_templates.py（应与 summarize.py 同目录）：{e}"
    ) from e

# 字段裁切顺序：先按句末标点断句，断不了再硬截
SENT_END = "。！？；"


def render_system(tpl: dict) -> str:
    """把声明式模板渲染成 system 提示。段间强制换行，避免指令粘连。"""
    lines = [f"[ROLE] {tpl['role']}",
             "[SCHEMA] 按此结构输出（下方是字段定义，勿照抄描述文字）："]
    for name, spec in tpl["schema"].items():
        bits = [spec.get("type", "string")]
        lo, hi = spec.get("min_chars"), spec.get("max_chars")
        if lo and hi:
            bits.append(f"{lo}–{hi} 字")
        elif hi:
            bits.append(f"≤{hi} 字")
        lines.append(f"  {name}: " + "，".join(bits))
    lines.append("[PREPROCESS] 依次执行：")
    for i, step in enumerate(tpl["preprocess"], 1):
        lines.append(f"  {i} {step}")
    lines.append(f"[STYLE] {tpl['style']}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 解析器
# 统一契约：parse(content) -> (dict, state, notes)
#   state ∈ {"ok", "repaired"}；抛 ParseError 表示失败
class ParseError(ValueError):
    pass


def _loads_loose(text: str) -> tuple[dict, bool]:
    """剥掉代码块围栏与前后噪声，返回 (dict, 是否修补过)。"""
    s = (text or "").strip()
    repaired = False
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        repaired = True
    a, b = s.find("{"), s.rfind("}")
    if a == -1 or b <= a:
        raise ParseError("响应中无 JSON 对象")
    if a > 0 or b < len(s) - 1:
        repaired = True
    try:
        obj = json.loads(s[a:b + 1])
    except json.JSONDecodeError as e:
        raise ParseError(f"JSON 解析失败: {e}") from e
    if not isinstance(obj, dict):
        raise ParseError("顶层不是对象")
    return obj, repaired


def parse_json_fields(content: str) -> tuple[dict, str, list[str]]:
    obj, repaired = _loads_loose(content)
    notes = ["已修补围栏/噪声"] if repaired else []
    return obj, ("repaired" if repaired else "ok"), notes


PARSERS = {"json_fields": parse_json_fields}


def validate_template(tid: str, tpl: dict) -> None:
    """单模板绑定检查：parser 名拼错、模板写残，都在这里暴露。"""
    p = tpl.get("parser")
    if p not in PARSERS:
        raise TemplateError(f"{tid}: parser={p!r} 未注册，可用: {sorted(PARSERS)}")
    if not tpl.get("schema"):
        raise TemplateError(f"{tid}: 未声明 schema")
    if "{{text}}" not in str(tpl.get("user", "")):
        raise TemplateError(f"{tid}: user 模板缺少 {{{{text}}}} 占位符")
    mp = map_spec(tpl)["parser"]
    if mp not in PARSERS:
        raise TemplateError(f"{tid}: map.parser={mp!r} 未注册，"
                            f"可用: {sorted(PARSERS)}")


def validate_templates() -> None:
    """启动期全量检查：一次把内置模板都验一遍。"""
    if DEFAULT_TEMPLATE not in TEMPLATES:
        raise TemplateError(f"DEFAULT_TEMPLATE={DEFAULT_TEMPLATE!r} 不在 "
                            f"TEMPLATES 里，可用: {sorted(TEMPLATES)}")
    for tid, tpl in TEMPLATES.items():
        validate_template(tid, tpl)


def resolve_template(template) -> tuple[str, dict]:
    """接受模板 ID 或已解析的 dict，返回 (id, 模板)。"""
    if isinstance(template, dict):
        tid = str(template.get("id") or "inline")
        validate_template(tid, template)
        return tid, template
    tid = str(template)
    if tid not in TEMPLATES:
        raise TemplateError(f"未知模板 {tid!r}，可用: {sorted(TEMPLATES)}")
    tpl = TEMPLATES[tid]
    validate_template(tid, tpl)
    return tid, tpl


def map_spec(tpl: dict) -> dict:
    """取模板的 map 段，缺省项由 DEFAULT_MAP 补齐。"""
    return {**DEFAULT_MAP, **(tpl.get("map") or {})}


def _fingerprint(tpl: dict) -> str:
    """提示词指纹：主提示 + map 提示 + 参数一起哈希。

    这样改任何一句文案，缓存自动失效，不依赖人记得升 version。
    """
    payload = json.dumps({
        "system": render_system(tpl),
        "map": map_spec(tpl).get("system"),
        "params": tpl.get("params"),
        "schema": tpl.get("schema"),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- 标签抽取
# 只匹配 #紧邻非空白 的写法，因此不会误吃 Markdown 标题「# 标题」。
TAG_RE = re.compile(r"#([^\s#，。、,.;:!?！？「」『』【】()（）\[\]<>\"'“”‘’|\\/]{1,20})")


def extract_tags(text: str, limit: int = 12) -> list[str]:
    """从原文抽取已有 hashtag。去重保序，不做繁简归并（保持忠于原文）。"""
    seen: set[str] = set()
    out: list[str] = []
    for m in TAG_RE.finditer(text or ""):
        body = m.group(1).strip().rstrip("-_ ")
        if not body or not re.search(r"[\w\u4e00-\u9fff]", body):
            continue
        key = body.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append("#" + body)
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- 配置
def load_config() -> tuple[str, str, str]:
    """从 ~/.claude/settings.json 取配置，并推导 OpenAI 兼容 base。"""
    env: dict = {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        env = data.get("env", {}) or {}
    except Exception:
        pass
    raw_base = (os.environ.get("DEEPSEEK_BASE_URL")
                or env.get("ANTHROPIC_BASE_URL")
                or "https://api.deepseek.com/anthropic")
    base = raw_base.rstrip("/")
    if base.endswith("/anthropic"):      # Anthropic 兼容端点带后缀，OpenAI 格式要去掉
        base = base[: -len("/anthropic")]
    token = (os.environ.get("DEEPSEEK_API_KEY")
             or env.get("ANTHROPIC_AUTH_TOKEN") or "")
    model = os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"
    return base, token, model


def is_peak(now: datetime | None = None) -> bool:
    """高峰：UTC 01–04、06–10，周一至周五（未含法定节假日，属近似）。"""
    now = now or datetime.now(timezone.utc)
    return now.weekday() < 5 and (1 <= now.hour < 4 or 6 <= now.hour < 10)


def cost_usd(model: str, hit: int, miss: int, out: int, peak: bool) -> float:
    p = PRICE.get(model, PRICE["deepseek-flash"])
    k = 2.0 if peak else 1.0
    return (hit * p["hit"] + miss * p["miss"] + out * p["out"]) / 1_000_000 * k


# ---------------------------------------------------------------- 文本准备
def prepare(text: str, max_chars: int) -> tuple[str, bool]:
    """超长文本按「头 60% + 尾 40%」采样，保留开头设定与结尾结论。"""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text, False
    head = int(max_chars * 0.6)
    tail = max_chars - head
    return (text[:head] + "\n……（中间内容已省略）……\n" + text[-tail:]), True


def split_chunks(text: str, size: int) -> list[str]:
    """按句末标点切块，尽量不切断句子。"""
    chunks, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？!?\n" and len(buf) >= size:
            chunks.append(buf)
            buf = ""
    if buf.strip():
        chunks.append(buf)
    return chunks or [text]


# ---------------------------------------------------------------- 调用
def chat(base: str, token: str, model: str, messages: list[dict],
         params: dict, max_tokens: int = 400, timeout: float = 60.0,
         retries: int = 1) -> tuple[str, dict, dict, dict]:
    """返回 (正文, 统计元数据, 原生响应, 请求体)。

    请求体与响应都原样保留，供备查。请求体只记 url + payload，
    鉴权头不进记录 —— token 不落盘、不进日志、不打屏。
    """
    url = f"{base}/v1/chat/completions"
    extra = dict(params)               # thinking / response_format 由模板给
    if isinstance(extra.get("thinking"), str):   # 模板写 "disabled"，接口要 {"type": ...}
        extra["thinking"] = {"type": extra["thinking"]}
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        **extra,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json",
               "authorization": f"Bearer {token}"}
    # 备查用：请求快照（不含 headers，避免 token 泄漏）
    req_snapshot = {"url": url, "payload": payload}

    last: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            t0 = time.perf_counter()
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = json.loads(r.read().decode("utf-8", errors="replace"))
            ms = (time.perf_counter() - t0) * 1000
            usage = raw.get("usage", {}) or {}
            choice = (raw.get("choices") or [{}])[0]
            meta = {
                "latency_ms": round(ms),
                "model": raw.get("model", model),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "cache_hit": usage.get("prompt_cache_hit_tokens", 0),
                "cache_miss": usage.get("prompt_cache_miss_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "finish_reason": choice.get("finish_reason"),
            }
            return (choice.get("message", {}).get("content", "") or ""), meta, raw, req_snapshot
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            last = RuntimeError(f"HTTP {e.code}: {detail}")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise last from e
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            last = RuntimeError(f"网络/超时: {e}")
            if attempt < retries:
                time.sleep(1.0 * (attempt + 1))
                continue
            raise last from e
    raise last or RuntimeError("未知错误")


# ---------------------------------------------------------------- 摘要流程
def summarize_once(text: str, tpl: dict, model: str,
                   base: str, token: str, timeout: float) -> dict:
    content, meta, raw, req = chat(
        base, token, model,
        [{"role": "system", "content": render_system(tpl)},
         {"role": "user", "content": tpl["user"].replace("{{text}}", text)}],
        params=tpl["params"],
        max_tokens=tpl["params"].get("max_tokens", 400),
        timeout=timeout,
    )
    obj, state, notes = PARSERS[tpl["parser"]](content)
    return {"obj": obj, "state": state, "notes": notes,
            "meta": meta, "raw_response": raw, "request": req,
            "content": content}


def summarize_chunked(text: str, tpl: dict, model: str,
                      base: str, token: str, chunk_chars: int,
                      timeout: float) -> dict:
    """超长文本：每块压成一句要点（map），再把要点归并成终稿（reduce）。

    map 阶段的指令来自模板的 map 段（缺省 DEFAULT_MAP），本函数不含业务措辞：
    换文体只改模板，不动这里。
    """
    spec = map_spec(tpl)
    parser = PARSERS[spec["parser"]]
    field = spec.get("field", "gist")

    # map 只继承 thinking；是否 JSON 模式取决于该阶段的解析器，不去蹭主模板的开关
    map_params: dict = {"thinking": tpl["params"].get("thinking", "disabled")}
    if spec["parser"] == "json_fields":
        map_params["response_format"] = {"type": "json_object"}

    chunks = split_chunks(text, chunk_chars)
    gists: list[str] = []
    total = {"prompt_tokens": 0, "completion_tokens": 0,
             "cache_hit": 0, "cache_miss": 0, "latency_ms": 0}
    sub_raws = []
    sub_reqs = []
    for c in chunks:
        content, m, raw, req = chat(
            base, token, model,
            [{"role": "system", "content": spec["system"]},
             {"role": "user", "content": c}],
            params=map_params,
            max_tokens=spec.get("max_tokens", 120),
            timeout=timeout)
        gists.append(parser(content)[0].get(field, ""))
        sub_raws.append(raw)
        sub_reqs.append(req)
        for k in total:
            total[k] += m.get(k, 0)

    merged = "\n".join(f"- {g}" for g in gists if g)
    final = summarize_once(merged, tpl, model, base, token, timeout)
    for k in total:
        total[k] += final["meta"].get(k, 0)
    total["chunks"] = len(chunks)
    total["calls"] = len(chunks) + 1          # 每块一次 + 归并一次
    total["model"] = final["meta"].get("model")
    total["finish_reason"] = final["meta"].get("finish_reason")
    return {**final, "meta": total, "chunk_raws": sub_raws,
            "chunk_reqs": sub_reqs}


def over_limit(obj: dict, tpl: dict) -> list[str]:
    """返回超出字数上限的字段名（超过 1.2 倍才值得再花一次调用去压）。"""
    out = []
    for name, spec in tpl["schema"].items():
        hi = spec.get("max_chars")
        if hi and len(str(obj.get(name) or "")) > hi * 1.2:
            out.append(name)
    return out


def compress_once(obj: dict, names: list[str], tpl: dict, model: str,
                  base: str, token: str, timeout: float) -> dict:
    """超限时压一次：把压缩交回模型，比客户端砍字更不丢要点。只含超限字段。"""
    limits = "；".join(f"{n}≤{tpl['schema'][n]['max_chars']}字" for n in names)
    sub = {n: obj.get(n, "") for n in names}
    content, meta, raw, req = chat(
        base, token, model,
        [{"role": "system", "content": tpl["role"]},
         {"role": "user",
          "content": f"把下列 JSON 的字段压缩到限制内（{limits}），"
                     "保留全部要点、不改事实、不新增内容。只输出同样结构的 JSON：\n"
                     + json.dumps(sub, ensure_ascii=False)}],
        params=tpl["params"],
        max_tokens=tpl["params"].get("max_tokens", 400),
        timeout=timeout,
    )
    out, _, _ = PARSERS[tpl["parser"]](content)
    return {**obj, **{k: v for k, v in out.items() if k in names},
            "_repair": True, "_repair_meta": meta, "_repair_raw": raw,
            "_repair_req": req}


def merge_meta(a: dict, b: dict) -> dict:
    out = dict(a)
    for k in ("prompt_tokens", "completion_tokens", "cache_hit", "cache_miss",
              "latency_ms", "total_tokens"):
        out[k] = a.get(k, 0) + b.get(k, 0)
    out["calls"] = a.get("calls", 1) + 1
    return out


def polish(res: dict, tpl: dict) -> tuple[dict, list[str]]:
    """按模板里的 constraints 收口长度。提示词管不住字数，代码必须兜底。"""
    warns: list[str] = []
    out: dict[str, str] = {}
    for name, spec in tpl["schema"].items():
        val = str(res.get(name) or "").strip()
        if spec.get("trim_punct"):
            val = val.rstrip("。．.，,；;、")
        hi, lo = spec.get("max_chars"), spec.get("min_chars")
        if hi and len(val) > hi:
            cut = val[:hi]
            if not spec.get("trim_punct"):
                # 只在上限附近（≥70%）找句末，避免为迁就一个早句号砍掉半篇
                i = max((cut.rfind(p) for p in SENT_END), default=-1)
                if i >= int(hi * 0.7):
                    cut = cut[:i + 1]
            warns.append(f"{name} 超长 {len(val)} 字 → 已截到 {len(cut)} 字")
            val = cut
        if lo and len(val) < lo:
            warns.append(f"{name} 仅 {len(val)} 字，低于 {lo} 字下限")
        out[name] = val
    return out, warns


# ---------------------------------------------------------------- 输出
def list_templates() -> int:
    """--list-templates：把可用模板摊开，不用翻代码记 ID。"""
    for tid, tpl in TEMPLATES.items():
        mark = "*" if tid == DEFAULT_TEMPLATE else " "
        fields = " / ".join(
            f"{n}→{spec['label']}" if spec.get("label") else n
            for n, spec in tpl["schema"].items())
        tags = "抽" if tpl.get("tags", True) else "不抽"
        print(f"{mark} {tid}  v{tpl['version']}  标签{tags}")
        print(f"    说明  {tpl.get('description', '')}")
        print(f"    字段  {fields}")
        print(f"    map   {'自定义' if tpl.get('map') else 'DEFAULT_MAP（中性措辞）'}")
    print("\n* = 默认模板（-t 省略时使用）；用 -t <ID> 指定其他模板")
    return 0


def show_request(req: dict, label: str) -> None:
    """把请求体打印成人可读的样子，供备查（逐条消息 + 字数 + 生效参数）。"""
    if not req:
        print(f"【{label}】 （缓存来自旧版本，未记录请求体）")
        return
    p = req.get("payload", {}) or {}
    think = p.get("thinking")
    think = think.get("type") if isinstance(think, dict) else think
    rf = p.get("response_format")
    print(f"【{label}】 {req.get('url')}")
    print(f"  model={p.get('model')}  max_tokens={p.get('max_tokens')}"
          f"  thinking={think}"
          + (f"  response_format={rf.get('type')}" if isinstance(rf, dict) else ""))
    for msg in p.get("messages", []):
        body = str(msg.get("content", ""))
        print(f"  ── {msg.get('role')}（{len(body)} 字）──")
        for line in body.splitlines() or [""]:
            print("  │ " + line)


def emit(out: dict, args) -> int:
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    tpl = TEMPLATES.get(out["meta"].get("template") or "") or {}
    print("=" * 56)
    # 字段按模板 schema 的顺序与 label 渲染，字段名不写死 —— 换模板即换输出形态
    schema = tpl.get("schema")
    if schema:
        for name, spec in schema.items():
            print(f"【{spec.get('label') or name}】", out.get(name, ""))
    else:   # 模板被删/改名：退回按结果里实际存在的字段渲染
        for name, val in out.items():
            if name not in ("tags", "meta", "raw"):
                print(f"【{name}】", val)
    if tpl.get("tags", True):
        print("【标签】", " ".join(out["tags"]) if out.get("tags")
              else "（原文无 hashtag）")

    m = out["meta"]
    for w in m.get("warnings", []):
        print("  ⚠ " + w)
    if m.get("parse_state") == "repaired":
        print("  ⚠ 模型输出非纯 JSON，已自动修补（提示词可再收紧）")

    if args.req:
        print("-" * 56)
        for i, r in enumerate(out["raw"].get("chunk_requests", []), 1):
            show_request(r, f"请求 · 分块 {i}")
        if out["raw"].get("chunk_requests"):
            print("-" * 56)
        show_request(out["raw"].get("request"), "请求 · 终稿")
        if out["raw"].get("repair_request"):
            print("-" * 56)
            show_request(out["raw"]["repair_request"], "请求 · 压缩重试")

    if args.raw:
        print("-" * 56)
        print("【原生返回】")
        print(out["raw"]["content"])
        if out["raw"].get("repair_response"):
            print("【压缩重试返回】")
            print(out["raw"]["repair_response"].get("choices", [{}])[0]
                  .get("message", {}).get("content", ""))

    if args.stats:
        print("-" * 56)
        print(f"模板      {m.get('template')} v{m.get('template_version')}")
        print(f"模型      {m.get('model')}  finish={m.get('finish_reason')}"
              f"  调用 {m.get('calls', 1)} 次"
              + ("（含压缩重试）" if m.get("repaired_by_model") else ""))
        print(f"输入字符  {m.get('in_chars')}"
              + ("（已截断）" if m.get("truncated") else "")
              + (f"（分块通读 {m.get('chunks')} 块）" if m.get("chunked") else ""))
        print(f"tokens    输入 {m.get('prompt_tokens')}"
              f"（命中 {m.get('cache_hit')} / 未命中 {m.get('cache_miss')}）"
              f" · 输出 {m.get('completion_tokens')}")
        print(f"耗时      {m.get('wall_ms')} ms"
              + ("（本地缓存命中，未调用 API）" if m.get("cached") else ""))
        print(f"费用      ${m.get('cost_usd', 0):.6f}"
              f" ≈ ¥{m.get('cost_usd', 0) * 7.1:.5f}"
              f"（{'高峰' if m.get('peak') else '低峰'}价）")
        print(f"响应 ID   {m.get('response_id')}")
    return 0


def write_audit(out: dict, template_id: str, digest: str, chars: int,
                tags: list[str], cached: bool = False, *,
                source: str | None = None, cache_dir=None) -> None:
    """追加一行审计。请求体与响应都取自 out["raw"]，缓存命中时也能留痕。"""
    cdir = pathlib.Path(cache_dir) if cache_dir else CACHE_DIR
    cdir.mkdir(parents=True, exist_ok=True)
    raw = out.get("raw") or {}
    line = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "template": template_id,
        "template_version": out["meta"].get("template_version"),
        "digest": digest,
        "chars": chars,
        "source": source,          # 处理的是哪个文件（库调用时很有用）
        "tags": tags,
        "cached": cached,
        "result": {k: out[k] for k in out if k not in ("tags", "meta", "raw")},
        "meta": out["meta"],
        "request": raw.get("request"),
        "raw_response": raw.get("response"),
    }
    with (cdir / "audit.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- 库接口
# 这一层是给 `import` 用的：传文件 + 模板名，拿字段字典。
# 失败一律抛异常（SummarizeError 家族），不 print、不 sys.exit。
#
#   from summarize import summarize_file
#   summarize_file("info.txt", "video_summary")   # -> {"overview": "...", "brief": "..."}
@dataclass
class SummaryResult:
    """一次摘要的完整结果。fields 就是 --raw 里那个 JSON 对象。"""
    fields: dict[str, str]
    tags: list[str]
    meta: dict
    raw: dict

    def to_dict(self) -> dict:
        """扁平结构（字段 + tags + meta + raw），与 --json / 缓存文件同构。"""
        return {**self.fields, "tags": self.tags, "meta": self.meta,
                "raw": self.raw}

    @classmethod
    def from_dict(cls, d: dict) -> "SummaryResult":
        return cls(fields={k: v for k, v in d.items()
                           if k not in ("tags", "meta", "raw")},
                   tags=list(d.get("tags") or []),
                   meta=dict(d.get("meta") or {}),
                   raw=dict(d.get("raw") or {}))


def read_text_file(path, encoding: str | None = "auto") -> str:
    """读正文文件。默认自动识别编码：utf-8-sig → gb18030，都不行就报错。

    Windows 上 GBK 编码的 txt 很常见。CLI 早期用 errors="replace" 会静默吞掉乱码，
    库调用不该这样 —— 宁可报错，也别交给用户一篇乱码的摘要。
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise InputError(f"文件不存在：{p}")
    if p.is_dir():
        raise InputError(f"这是目录不是文件：{p}")
    raw = p.read_bytes()
    if encoding and encoding != "auto":
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as e:
            raise InputError(f"按 {encoding} 解码失败：{e}") from e
    for enc in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise InputError(f"无法识别文件编码（试过 utf-8-sig / gb18030）：{p}")


def run_text(text: str, template=DEFAULT_TEMPLATE, *, source: str | None = None,
             max_chars: int = 8000, chunk: bool = False, chunk_chars: int = 3000,
             timeout: float = 60.0, cache: bool = False, audit: bool = False,
             model: str | None = None, base_url: str | None = None,
             api_key: str | None = None, cache_dir=None) -> SummaryResult:
    """核心流水线：文本 → 字段。CLI 与库调用共用这一份逻辑，不存在两条路径。"""
    text = (text or "").strip()
    if not text:
        raise InputError("没有输入文本：文件为空，或传入的字符串是空白")
    tid, tpl = resolve_template(template)

    cfg_base, cfg_token, cfg_model = load_config()
    base = base_url or cfg_base
    token = api_key or cfg_token
    model = model or cfg_model
    if not token:
        raise InputError("未找到 API Key：设环境变量 DEEPSEEK_API_KEY，"
                         "或写进 ~/.claude/settings.json 的 env.ANTHROPIC_AUTH_TOKEN")
    cdir = pathlib.Path(cache_dir) if cache_dir else CACHE_DIR

    # 标签从原文抽，与模型无关 —— 所以缓存键与输出都必须覆盖原文
    tags = extract_tags(text)

    # 缓存键：模板 id + 版本 + 提示词指纹 + 模型 + 原文
    digest = hashlib.sha256(
        f"{tid}|v{tpl['version']}|{_fingerprint(tpl)}|{model}|{text}"
        .encode("utf-8")
    ).hexdigest()[:16]
    cache_file = cdir / f"{digest}.json"

    if cache and cache_file.exists():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cached = None            # 缓存坏了当没有，别让一个坏文件毁掉整次调用
        if cached:
            cached["meta"]["cached"] = True
            cached["meta"]["wall_ms"] = 0
            cached["meta"]["cost_usd"] = 0.0
            result = SummaryResult.from_dict(cached)
            if audit:                # 命中也要留痕，否则 --cache --audit 二次为空
                write_audit(result.to_dict(), tid, digest, len(text), tags,
                            cached=True, source=source, cache_dir=cdir)
            return result

    payload, truncated = prepare(text, max_chars)
    chunked = bool(chunk and len(text) > max_chars)
    t0 = time.perf_counter()
    try:
        if chunked:
            res = summarize_chunked(text, tpl, model, base, token,
                                    chunk_chars, timeout)
        else:
            res = summarize_once(payload, tpl, model, base, token, timeout)
    except SummarizeError:
        raise
    except ParseError as e:
        raise ApiError(f"模型输出无法解析：{e}") from e
    except Exception as e:                       # HTTP / 超时 / 其他
        raise ApiError(str(e)) from e

    first_raw = res["raw_response"]
    repair_raw = None
    repair_req = None
    warns: list[str] = []
    # 只对「明显超限」的字段再压一次；压缩失败就退回客户端截断，绝不因此报错
    over = over_limit(res["obj"], tpl)
    if over:
        try:
            fixed = compress_once(res["obj"], over, tpl, model, base, token,
                                  timeout)
            res["obj"] = {k: v for k, v in fixed.items() if not k.startswith("_")}
            res["meta"] = merge_meta(res["meta"], fixed["_repair_meta"])
            repair_raw = fixed["_repair_raw"]
            repair_req = fixed["_repair_req"]
        except Exception as e:                   # 不再 print，收进 warnings
            warns.append(f"压缩重试失败，已改用截断：{e}")

    fields, polish_warns = polish(res["obj"], tpl)
    warns += polish_warns
    peak = is_peak()
    meta = {
        **res["meta"],
        "template": tid,
        "template_version": tpl["version"],
        "parse_state": res["state"],
        "parse_notes": res["notes"],
        "wall_ms": round((time.perf_counter() - t0) * 1000),
        "in_chars": len(text),
        "chunked": chunked,
        "truncated": truncated and not chunked,   # 分块时是通读，不是截断
        "peak": peak,
        "cost_usd": round(cost_usd(model,
                                   res["meta"].get("cache_hit", 0),
                                   res["meta"].get("cache_miss", 0),
                                   res["meta"].get("completion_tokens", 0),
                                   peak), 8),
        "cached": False,
        "response_id": first_raw.get("id"),
        "calls": res["meta"].get("calls", 1),
        "repaired_by_model": bool(repair_raw),
        "warnings": warns,
    }

    result = SummaryResult(
        fields=fields,
        tags=tags,
        meta=meta,
        # 请求体：实际发出去的 url + payload（不含鉴权头），供备查
        # 响应：原生返回原样保留（--json 可整体重定向到文件）
        raw={
            "request": res["request"],
            "content": res["content"],
            "response": first_raw,
            **({"repair_request": repair_req} if repair_req else {}),
            **({"repair_response": repair_raw} if repair_raw else {}),
            # 分块模式下每一块的请求/响应，缺省不出现
            **({"chunk_requests": res["chunk_reqs"]}
               if res.get("chunk_reqs") else {}),
            **({"chunk_responses": res["chunk_raws"]}
               if res.get("chunk_raws") else {}),
        },
    )

    if cache:
        cdir.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_name(cache_file.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, cache_file)   # 原子替换：并发调用不会读到半个文件

    if audit:
        write_audit(result.to_dict(), tid, digest, len(text), tags,
                    source=source, cache_dir=cdir)

    return result


def run_file(path, template=DEFAULT_TEMPLATE, *, encoding="auto",
             **kwargs) -> SummaryResult:
    """读文件 → 跑流水线。其余参数原样透传给 run_text。"""
    return run_text(read_text_file(path, encoding), template,
                    source=str(path), **kwargs)


def summarize_file(path, template=DEFAULT_TEMPLATE, **kwargs) -> dict[str, str]:
    """你要的那个方法：文件名 + 模板名 → 字段字典（与 --raw 的 JSON 同形）。

        summarize_file("info.txt", "video_summary")
        # {"overview": "……", "brief": "……"}
    """
    return run_file(path, template, **kwargs).fields


def summarize_text(text, template=DEFAULT_TEMPLATE, **kwargs) -> dict[str, str]:
    """同 summarize_file，但输入是字符串 —— 测试、临时文本不用造文件。"""
    return run_text(text, template, **kwargs).fields


# ---------------------------------------------------------------- 命令行
def main() -> int:
    ap = argparse.ArgumentParser(description="DeepSeek 文档摘要（模板化 + 省 token）")
    ap.add_argument("text", nargs="*", help="直接传入原文")
    ap.add_argument("-f", "--file", help="从文件读原文（-f - 表示 stdin）")
    ap.add_argument("-t", "--template", default=DEFAULT_TEMPLATE,
                    choices=sorted(TEMPLATES),
                    help=f"模板 ID（默认 {DEFAULT_TEMPLATE}，见 --list-templates）")
    ap.add_argument("--list-templates", action="store_true",
                    help="列出所有可用模板、字段与默认值")
    ap.add_argument("--json", action="store_true",
                    help="输出 JSON（含请求体与原生响应，可重定向留档）")
    ap.add_argument("--raw", action="store_true", help="打印模型原生返回内容")
    ap.add_argument("--req", action="store_true",
                    help="打印实际发出去的请求体（url + messages + 参数），供备查")
    ap.add_argument("--stats", action="store_true", help="打印 token 与费用")
    ap.add_argument("--chunk", action="store_true", help="超长文本分块摘要再归并")
    ap.add_argument("--max-chars", type=int, default=8000)
    ap.add_argument("--chunk-chars", type=int, default=3000)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--cache", action="store_true", help="按原文哈希缓存，重复不调用")
    ap.add_argument("--audit", action="store_true",
                    help="追加一条记录（含请求体与响应）到 .cache/audit.jsonl")
    args = ap.parse_args()

    try:
        validate_templates()
        if args.list_templates:
            return list_templates()

        if args.file:
            text = (sys.stdin.read() if args.file == "-"
                    else read_text_file(args.file))
            source = None if args.file == "-" else args.file
        else:
            text = " ".join(args.text).strip() or sys.stdin.read()
            source = None

        result = run_text(text, args.template, source=source,
                          max_chars=args.max_chars, chunk=args.chunk,
                          chunk_chars=args.chunk_chars, timeout=args.timeout,
                          cache=args.cache, audit=args.audit)
    except TemplateError as e:
        print(f"[模板错误] {e}", file=sys.stderr)
        return e.exit_code
    except InputError as e:
        print(f"[输入错误] {e}", file=sys.stderr)
        return e.exit_code
    except ApiError as e:
        print(f"[失败] {e}", file=sys.stderr)
        return e.exit_code
    except SummarizeError as e:          # 兜底：以后新增的异常也不会抛栈
        print(f"[失败] {e}", file=sys.stderr)
        return e.exit_code

    return emit(result.to_dict(), args)


if __name__ == "__main__":
    sys.exit(main())

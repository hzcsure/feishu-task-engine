# 操作文档 · summarize.py

> 这份文档只讲**怎么用、怎么改、出问题怎么查**。
> 设计与省 token 原理见同目录 `README.md`。

---

## 1. 一分钟上手

```bash
cd claude-handoff/06-summarize

# 最常用：给一个文件，看结果
python summarize.py -f info.txt

# 看有哪些模板 / 换模板
python summarize.py --list-templates
python summarize.py -f sample-meeting.txt -t meeting_notes

# 看 token 与费用
python summarize.py -f info.txt --stats

# 机器可读（含请求体与原生响应，可重定向留档）
python summarize.py -f info.txt --json > out.json

# 看实际发出去的请求体（system/user 原文 + 生效参数）
python summarize.py -f info.txt --req

# 管道
type info.txt | python summarize.py
```

零依赖，Python 3.8+ 直接跑。凭据自动从 `~/.claude/settings.json` 的 `env` 读
（`ANTHROPIC_AUTH_TOKEN`），也可用环境变量覆盖（见 §3）。

输出三行：

```
【概述】 100 字以内的正文概述
【简述】 16 字以内的小标题
【标签】 #影評 #電影 #电影解说 #電影解說
```

---

## 2. 参数表

| 参数 | 作用 | 备注 |
|---|---|---|
| `-f, --file` | 输入文件；`-f -` 读 stdin | 二选一 |
| `文本...` | 直接传一段文字 | 与 `-f` 二选一 |
| `-t, --template` | 选模板 ID | 内置 `video_summary` / `meeting_notes` |
| `--list-templates` | 列出模板、字段、默认值 | 忘了 ID 就跑这个 |
| `--json` | 输出 JSON（含 `raw` 请求体 + 原生响应） | 留档首选 |
| `--raw` | 打印模型原生返回内容 | 排查「为什么它这么写」 |
| `--req` | 打印实际发出去的请求体 | 排查「它到底收到了什么」 |
| `--stats` | 打印模板/模型/token/耗时/费用/响应 ID | |
| `--cache` | 按「模板+版本+模型+原文」哈希缓存 | 重复调用 0 成本 |
| `--audit` | 追加一条记录到 `.cache/audit.jsonl` | 长期留痕 |
| `--chunk` | 超长文本分块摘要再归并 | 更完整、更贵 |
| `--max-chars` | 单次送入上限，默认 8000 | 超出按头 60%/尾 40% 采样 |
| `--chunk-chars` | 分块大小，默认 3000 | 配合 `--chunk` |
| `--timeout` | 单次请求超时秒数，默认 60 | |

退出码：`0` 成功 / `1` 参数或配置错误 / `2` 调用失败（含 401、超时）。

---

## 3. 凭据与端点

读取顺序：

1. `DEEPSEEK_API_KEY` 环境变量
2. `~/.claude/settings.json` → `env.ANTHROPIC_AUTH_TOKEN`

端点读取顺序：

1. `DEEPSEEK_BASE_URL`
2. `env.ANTHROPIC_BASE_URL`，自动去掉结尾的 `/anthropic`
3. 兜底 `https://api.deepseek.com`

模型：`DEEPSEEK_MODEL` 覆盖，默认 `deepseek-flash`。

> 验证失败路径：`DEEPSEEK_API_KEY=sk-invalid python summarize.py -f info.txt`，
> 应看到 `[失败] HTTP 401 ...` 且退出码为 `2`（不会抛栈、不会写出半截缓存）。

---

## 4. 标签（`#标签`）的规则

**从原文抽取，不让模型生成。** 这是刻意的设计：

- 提示词里完全不提标签 → 不占输入 token、不占输出 token
- 模型没有机会编造一个原文里不存在的 tag
- 抽取在客户端做，规则确定、可复现

实现要点（`extract_tags()`）：

| 规则 | 说明 |
|---|---|
| 匹配 `#紧邻非空白` | 所以 Markdown 标题「`# 标题`」不会被误吃 |
| 截止符 | 空白、`#`、中英文标点、引号、括号、斜杠都不进标签 |
| 去重 | 按 `#` 后正文 `casefold` 去重，**保序**（只留首次出现） |
| 繁简不合并 | `#电影解说` 与 `#電影解說` 都保留，忠于原文 |
| 上限 | 12 个 |
| 豁免 | `C#`、纯符号不会成为标签 |

原文没有 hashtag 时输出「（原文无 hashtag）」，`tags` 为 `[]`，**不会补造**。

实测（`info.txt`）：
```
#影評  #電影  #电影解说  #電影解說
```

---

## 5. 请求体与响应（备查）

一次调用有两个方向，都留档：**发出去的**（`raw.request`）和**收回来的**（`raw.response`）。

| 方式 | 拿到什么 | 场景 |
|---|---|---|
| `--json` | 全部：`raw.request` + `raw.content` + `raw.response`（`id`/`created`/`model`/`choices`/`usage`/`system_fingerprint`） | 单次留档，重定向成文件 |
| `--req` | 请求体打印成人可读版：url、生效参数、逐条消息与字数 | 核对「提示词真的按模板渲染了吗」 |
| `--raw` | 只打印 `raw.content` | 人眼快看「它到底写了什么」 |
| `--audit` | 追加一行到 `.cache/audit.jsonl`（含 `request` 与 `raw_response`） | 长期留痕、批量后回顾 |

`--req` 实测输出（`sample-transcript.txt`，812 字正文）：

```
【请求 · 终稿】 https://api.deepseek.com/v1/chat/completions
  model=deepseek-flash  max_tokens=400  thinking=disabled  response_format=json_object
  ── system（270 字）──
  │ [ROLE] 你是摘要器，只输出 JSON，不解释、不加代码块。
  │ [SCHEMA] 按此结构输出（下方是字段定义，勿照抄描述文字）：
  │   overview: string，50–100 字
  │   brief: string，≤16 字
  │ [PREPROCESS] 依次执行：
  │   1 删除推广、会员、订阅、投稿、联系方式、外链与频道自述
  │   2 删除时长、分辨率、文件大小、下载时间等元数据
  │   3 若清洗后无正文，overview 与 brief 均填「无正文」
  │ [STYLE] 简体中文；brief 不加标点；不输出字数统计；不加代码块。
  ── user（812 字）──
  │ 原文：
  │ 大家好，今天我们聊一个很多人都关心的问题……
```

`raw` 的 JSON 结构（键按出现条件出现）：

```json
"raw": {
  "request":        {"url": "...", "payload": {"model": "...", "messages": [...],
                                               "max_tokens": 400,
                                               "thinking": {"type": "disabled"},
                                               "response_format": {"type": "json_object"}}},
  "content":        "模型输出的正文（字符串）",
  "response":       {完整响应体},
  "repair_request": {压缩重试的请求体},      // 仅触发压缩重试时
  "repair_response": {…},                    // 仅触发压缩重试时
  "chunk_requests": [{分块 1 请求}, …],      // 仅 --chunk 时
  "chunk_responses": [{分块 1 响应}, …]      // 仅 --chunk 时
}
```

`--chunk` 时 `--req` 会依次打印「分块 1..N → 终稿 → 压缩重试」每一段，
分块段与终稿段的参数差异一眼可辨（`max_tokens` 120 vs 400，system 也不一样）。

> **token 不落盘**：请求快照只记 `url` + `payload`，`authorization` 头不进记录，
> 因此 `--json` / `--cache` / `--audit` 的任何产物都可以直接贴给别人看。
> 缓存命中时（`--cache`）同样能打印请求体 —— 它随缓存文件一起存着。

审计记录字段：

```json
{"ts":"...","template":"video_summary","template_version":5,"digest":"...",
 "chars":3052,"tags":["#影評"],"cached":false,
 "result":{"overview":"...","brief":"..."},"meta":{...},
 "request":{"url":"...","payload":{...}},"raw_response":{...}}
```

`digest` 与缓存键同源，可用它对上某次缓存文件。
缓存命中时也会写一行（`cached: true`、`cost_usd: 0`），请求体照旧可查 ——
所以 `--cache --audit` 连续跑两次，日志里是两行、不是一行。

> 触发过压缩重试时，`raw.repair_response` 里会有第二次调用的完整响应，
> `raw.repair_request` 里有它的请求体，`meta.calls` 为 2，
> `meta.repaired_by_model` 为 `true`。

---

## 6. 模板与绑定

### 6.1 文件分工

| 文件 | 放什么 | 什么时候动它 |
|---|---|---|
| `summary_templates.py` | **纯声明**：`TEMPLATES` / `DEFAULT_MAP` / `DEFAULT_TEMPLATE` | 改文案、加模板、调字数上限 —— 只动这里 |
| `summarize.py` | 渲染提示、校验绑定、调 API、收口长度、打印 | 只有新增**解析器**时才动 |

`summarize.py` 启动时 `from summary_templates import TEMPLATES, DEFAULT_MAP, DEFAULT_TEMPLATE`，
同目录找不到就直接报错退出（不会带着空模板跑）。代码里已经没有任何文体措辞。

### 6.2 一份模板长什么样

```python
"video_summary": {
    "version": 6,                      # 文案版本，改文案就 +1
    "description": "口播稿 → 100 字概述 + 16 字小标题",   # --list-templates 显示
    "params": {"thinking": "disabled", "max_tokens": 400,
               "response_format": {"type": "json_object"}},
    "role": "你是摘要器，只输出 JSON……",                  # → [ROLE]
    "schema": {                                            # → [SCHEMA]，也是打印顺序
        "overview": {"type": "string", "min_chars": 50, "max_chars": 100,
                     "label": "概述"},
        "brief":    {"type": "string", "max_chars": 16, "trim_punct": True,
                     "label": "简述"},
    },
    "preprocess": ["删除推广、会员……", "删除元数据……"],      # → [PREPROCESS] 编号列表
    "style": "简体中文；brief 不加标点……",                 # → [STYLE]
    "user": "原文：\n{{text}}",                            # ← 必须含 {{text}}
    "parser": "json_fields",                               # ← 终稿解析器，启动期校验
    "map": {                                               # ← 可选：分块时「一块 → 一句要点」
        "system": '把这段口播稿压成一句话要点，只输出JSON：{"gist":"..."}',
        "parser": "json_fields",
        "field": "gist",
        "max_tokens": 120,
    },
    "tags": True,                      # 可选，默认 True；False 则不打印【标签】
}
```

各键的作用：

| 键 | 必填 | 作用 | 漏了会怎样 |
|---|---|---|---|
| `version` | ✓ | 版本号，进缓存键 | 缓存键里还有指纹兜底 |
| `description` | — | `--list-templates` 里的说明 | 显示空 |
| `params` | ✓ | 请求参数（`thinking` / `max_tokens` / `response_format`） | 取默认 400，思考模式不关 → 变贵 |
| `role` | ✓ | 角色设定 | 渲染出 `[ROLE] None`，模型容易跑偏 |
| `schema` | ✓ | 字段表 + 字数上下限 + 打印用的 `label` | **启动即报错** |
| `preprocess` | ✓ | 清洗步骤（按序号渲染） | 启动即报错（`KeyError`） |
| `style` | ✓ | 文体与格式要求 | 同上 |
| `user` | ✓ | 用户消息模板 | 缺 `{{text}}` → **启动即报错** |
| `parser` | ✓ | 终稿解析器名 | 未注册 → **启动即报错** |
| `map` | — | 分块阶段的指令 | 回退 `DEFAULT_MAP`（措辞中性） |
| `tags` | — | 是否打印标签行 | 默认 True |

`label` 只用于**打印**（`【概述】`），不进提示词 —— 所以换中文标签不影响 token 与缓存指纹。

### 6.3 多模板：支持，内置两个

`TEMPLATES` 是普通 dict，key 就是模板 ID。内置：

| ID | 用途 | 字段 | 标签 |
|---|---|---|---|
| `video_summary`（默认） | 口播稿 / 视频信息 | `overview` / `brief` | 抽 |
| `meeting_notes` | 会议记录 | `conclusion` / `actions` / `title` | 不抽 |

两个模板字段名完全不同 —— 输出是按各模板 `schema` 渲染的，代码里没有 `【概述】`
这种写死的打印。想看清单：

```bash
python summarize.py --list-templates
```

```
* video_summary  v6  标签抽
    说明  口播稿 / 视频信息 → 100 字概述 + 16 字小标题（标签另从原文抽取）
    字段  overview→概述 / brief→简述
    map   自定义
  meeting_notes  v1  标签不抽
    说明  会议记录 → 90 字结论 + 待办 + 14 字标题（不抽标签）
    字段  conclusion→结论 / actions→待办 / title→标题
    map   自定义

* = 默认模板（-t 省略时使用）；用 -t <ID> 指定其他模板
```

### 6.4 模板怎么「绑定」（三种方式，优先级递减）

| # | 方式 | 写法 | 适用 |
|---|---|---|---|
| 1 | 命令行 `-t` | `python summarize.py -f a.txt -t meeting_notes` | 临时换、批处理脚本里逐条指定 |
| 2 | 改默认值 | `summary_templates.py` 里 `DEFAULT_TEMPLATE = "meeting_notes"` | 某一阵子主用某个文体 |
| 3 | 薄包装 | 写个 `run.sh` / 别名，把 `-t` 固定住 | 给非技术同事用 |

```bash
python summarize.py -f sample-meeting.txt -t meeting_notes          # 会议纪要
python summarize.py -f sample-transcript.txt                        # 走默认 video_summary
```

**绑定是「整条链路」的，不只换提示词**：

| 环节 | 绑定到哪个字段 |
|---|---|
| system 提示 | `role` / `schema` / `preprocess` / `style` |
| user 消息 | `user`（`{{text}}` 处塞原文） |
| 请求参数 | `params`（`max_tokens` / `thinking` / `response_format`） |
| 解析器 | `parser`（终稿）、`map.parser`（分块） |
| 分块指令 | `map.system`（缺省 `DEFAULT_MAP`） |
| 打印形态 | `schema[*].label`、`tags` |
| 缓存键 | `template_id` + `version` + 提示词指纹 + 模型 + 原文 |

所以**换模板不会串缓存**：同一份原文分别用两个模板跑，`--cache` 下是两份独立结果
（实测：`sample-meeting.txt` 用 `meeting_notes` 得到结论/待办/标题，
用 `video_summary` 得到概述/简述/标签，互不覆盖）。

### 6.5 新增一个模板（三步，不动 summarize.py）

1. 复制 `summary_templates.py` 里任意一份 dict，改 key（= 新模板 ID）
2. 改 `schema`（字段名随你取，`label` 决定打印标题）、`role`、`preprocess`、`style`、`user`
3. 验证：

```bash
python summarize.py --list-templates                      # 能不能读出来
python summarize.py -f 样本.txt -t 新ID --req              # 提示词渲染对不对
python summarize.py -f 样本.txt -t 新ID --stats            # 字数收口、费用
```

一个最小模板（不吃 `map`，分块时自动用中性的 `DEFAULT_MAP`）：

```python
"tweet": {
    "version": 1,
    "description": "长文 → 一条推文（≤60 字）",
    "params": {"thinking": "disabled", "max_tokens": 200,
               "response_format": {"type": "json_object"}},
    "role": "你是社媒编辑，只输出 JSON。",
    "schema": {"post": {"type": "string", "max_chars": 60, "label": "推文"}},
    "preprocess": ["删除推广与元数据", "无正文则填「无正文」"],
    "style": "简体中文；不加 hashtag；不加代码块。",
    "user": "原文：\n{{text}}",
    "parser": "json_fields",
    "tags": False,
},
```

### 6.6 新增一个解析器（唯一需要动 summarize.py 的情况）

当模型输出不是「纯 JSON 对象」时（比如要塞进 XML、或要二次抽取），才需要写解析器：

```python
def parse_my_thing(content):
    obj, repaired = _loads_loose(content)
    return obj, ("repaired" if repaired else "ok"), []

PARSERS["my_thing"] = parse_my_thing
```

契约固定：`parse(content) -> (dict, state, notes)`，`state ∈ {"ok","repaired"}`，
失败抛 `ParseError`。注册后模板里写 `"parser": "my_thing"` 即可，启动期自动校验。

### 6.7 三条纪律

1. `version` 建议随文案递增；即便忘了，缓存键里已含**提示词指纹**
   （`_fingerprint()` 覆盖 system / map / params / schema），改一个字也会自动失效
2. `schema` 里写的 `max_chars` 就是收口依据，不要另在代码里硬编码
3. `parser` 与 `map.parser` 必须是 `PARSERS` 里已注册的名字，否则启动即报错

渲染成 system 提示后长这样（段间强制换行，避免指令粘连）：

```
[ROLE] 你是摘要器，只输出 JSON，不解释、不加代码块。
[SCHEMA] 按此结构输出（下方是字段定义，勿照抄描述文字）：
  overview: string，50–100 字
  brief: string，≤16 字
[PREPROCESS] 依次执行：
  1 删除推广、会员、订阅、投稿、联系方式、外链与频道自述
  2 删除时长、分辨率、文件大小、下载时间等元数据
  3 若清洗后无正文，overview 与 brief 均填「无正文」
[STYLE] 简体中文；brief 不加标点；不输出字数统计；不加代码块。
```

**`map` 段为什么单独存在**：`--chunk` 会先把长文切成块，每块压成一句要点，再归并成终稿。
这段指令属于「文体相关」的业务措辞（口播稿/合同/财报…），因此放在模板里，代码只负责编排。
省略 `map` 时使用 `DEFAULT_MAP`（措辞中性：「把这段文本压成一句话要点」）。

> 换文体只需改 `map.system`，`summarize_chunked` 一行不用动。
> 实测：`meeting_notes` 的 `map.system` 是「把这段会议记录压成一句要点」，
> `--chunk` 时三块都用它，快照里可直接核对。

---

## 7. 长度收口（提示词管不住，代码兜底）

| 情况 | 处理 |
|---|---|
| 字段超上限 **1.2 倍** | 触发**一次压缩重试**（把压缩交回模型，只压超限字段），更不易丢要点 |
| 压缩后仍超 | 客户端截断：优先在上限 70% 之后的最近句末断，否则按上限硬截 |
| 概述低于 50 字 | 仅告警，不补写（避免注水） |
| `brief` | 去掉句末标点后按 16 字硬截 |

实测：816 字口播稿首次输出 138 字概述 → 触发压缩重试 → 119 字 → 截到 90 字，
`老板停留时间翻倍` 这类结论得以保留（旧版硬截会砍掉一半内容）。

---

## 8. 演示（两个模板各跑一次）

```bash
python summarize.py -f info.txt --cache --audit --stats            # 默认：video_summary
python summarize.py -f sample-meeting.txt -t meeting_notes --stats # 换模板：会议记录
```

本机实测输出（`video_summary`）：

```
【概述】 该视频为影视解说频道「光影二三事」对一部日本电影的剧情讲解，标题以长泽雅美主演、
         男友身份全假的悬疑情感设定为看点，讲述同居五年后揭露对方身份、姓名均为虚假的感人故事。
【简述】 长泽雅美悬疑情感电影解说
【标签】 #影評 #電影 #电影解说 #電影解說
模板      video_summary v6
模型      deepseek-flash  finish=stop  调用 1 次
输入字符  3052
tokens    输入 1359（命中 1152 / 未命中 207） · 输出 69
耗时      1876 ms
费用      $0.000076 ≈ ¥0.00054（低峰价）
```

同一份原文换 `-t meeting_notes`（`sample-meeting.txt`，712 字）：

```
【结论】 本期决定不做批量导入、顺延至下个迭代，12月8日按主流程提测；筛选器位置争议
         留待用户测试判定；看板口径错误已修正需同步变更；推送服务测试环境为关键风险。
【待办】 陈可周五前补埋点字段；张岚本周内协调推送环境并对齐销售预期；赵旗周三前备测试脚本
【标题】 产品周会决议与风险
--------------------------------------------------------
模板      meeting_notes v1
模型      deepseek-flash  finish=stop  调用 1 次
输入字符  712
tokens    输入 681（命中 0 / 未命中 681） · 输出 105
耗时      1568 ms
费用      $0.000165 ≈ ¥0.00117（低峰价）
```

注意两点：**字段名与标题全变了**（没有 `【概述】`，也没有 `【标签】` 行），
但命令只多了一个 `-t`；**没有一行代码为会议纪要改过**。

同一份文件再跑一次（`--cache`）：**0 ms、$0**（审计里仍会记一行 `cached: true`）。

---

## 9. 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `HTTP 401` | token 无效/未读到 | 检查 `~/.claude/settings.json` 的 `env.ANTHROPIC_AUTH_TOKEN` |
| `HTTP 422 … thinking: invalid type` | `thinking` 传了字符串 | 已修：模板写 `"disabled"`，调用层转 `{"type":"disabled"}` |
| `[模板错误] xxx: parser=... 未注册` | 模板 `parser` 名拼错 | 改成 `PARSERS` 里的名字 |
| 概述明显变短 | 触发了截断 | 看 `⚠` 告警与 `--raw`；调高模板 `max_chars` 或改 `preprocess` |
| `[模板错误] 无法加载 summary_templates.py` | 文件不在同目录 / 模块内有语法错 | 放回同目录；`python -c "import summary_templates"` 看真实报错 |
| `[模板错误] xxx: user 模板缺少 {{text}}` | 占位符被删掉了 | 在 `user` 里补 `{{text}}` |
| `[模板错误] DEFAULT_TEMPLATE=… 不在 TEMPLATES 里` | 改了模板 ID 却没改默认值 | 两边对齐 |
| 某个字段一直是空的 | 模板 `schema` 的键名与模型输出不一致 | `--raw` 看模型实际返回什么键 |
| 输出带 ``` 围栏 | 模型没守格式 | 自动修补并在 `⚠` 提示；`meta.parse_state=repaired` |
| 结果和上次不同但内容没改 | 模板 `version` 没变却改了文案 | 升 `version` 重跑 |
| 摘要里出现推广句子 | `preprocess` 描述不够具体 | 往 `preprocess` 加一条明确禁令 |

---

## 10. 成本速查

| 场景 | 实测 |
|---|---|
| 3052 字视频信息 | 输入 1359（命中 1152）· 输出 67 · **¥0.0011** · 1.7 s |
| 816 字口播稿 | 输入 667 · 输出 77 · ¥0.0021 · 1.1 s |
| 712 字会议记录（`meeting_notes`） | 输入 681 · 输出 105 · ¥0.0012 · 1.6 s |
| 同上 + 压缩重试 | 输入 827 · 输出 178 · ¥0.0022 · 3.3 s |
| 二次（本地缓存） | **¥0** · 0 ms |

批量建议：`--cache --audit`，并把任务排在 **UTC 16:00 之后**（低峰，价格减半）。

---

## 11. 作为库调用（不经过命令行）

同一个流水线，两种入口：CLI 给人和脚本，库接口给 Python 代码。二者共用
`run_text()`，不存在“命令行能跑、import 跑不通”的第二条路径。

### 11.1 你要的那个方法

```python
from summarize import summarize_file

data = summarize_file("info.txt", "video_summary")
# {"overview": "……", "brief": "……"}
```

等价于 `python summarize.py -f info.txt --raw` 里那个 JSON 对象 —— 只有模板
`schema` 里声明的字段，没有 `tags` / `meta` / `raw` 这些附加信息。

| 函数 | 输入 | 返回 |
|---|---|---|
| `summarize_file(path, template="video_summary", **kw)` | 文件路径 | `dict[str, str]` 只要字段 |
| `summarize_text(text, template=…, **kw)` | 字符串 | 同上（测试不用造文件） |
| `run_file(path, template=…, **kw)` | 文件路径 | `SummaryResult`（字段 + tags + meta + raw） |
| `run_text(text, template=…, **kw)` | 字符串 | 同上 |

`template` 也可以是已经解析好的 dict（高级用法，跳过内置查找）。

### 11.2 关键字参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `max_chars` | 8000 | 单次送入上限，超出按头 60% / 尾 40% 采样 |
| `chunk` / `chunk_chars` | False / 3000 | 超长分块再归并（`len(text) > max_chars` 才生效） |
| `timeout` | 60.0 | 单次请求超时秒数 |
| `cache` | False | 本地结果缓存（库默认关：调用方要可预期的行为） |
| `audit` | False | 追加一行到 `<cache_dir>/audit.jsonl` |
| `model` / `base_url` / `api_key` | None | 覆盖 `~/.claude/settings.json` 与 `DEEPSEEK_*` 环境变量 |
| `cache_dir` | 脚本同目录 `.cache` | 换缓存/审计落点，多进程隔离时有用 |
| `encoding` | `"auto"` | 仅 `run_file`/`summarize_file`：utf-8-sig → gb18030 自动识别 |

### 11.3 失败一定是异常，不是退出进程

```python
from summarize import summarize_file, InputError, TemplateError, ApiError

try:
    data = summarize_file("info.txt", "video_summary")
except TemplateError as e:      # 模板名错、schema 缺、parser 未注册
    ...
except InputError as e:         # 文件不存在 / 编码认不出 / 正文为空 / 没有 Key
    ...
except ApiError as e:           # HTTP 错误 / 超时 / 响应不是 JSON
    ...
```

| 异常 | `exit_code` | 触发场景 |
|---|---|---|
| `TemplateError` | 1 | 模板不存在、`schema` 空、`parser` 未注册、缺 `{{text}}` |
| `InputError` | 1 | 文件不存在/是目录、解码失败、正文空白、无 API Key |
| `ApiError` | 2 | 401/422/5xx、超时、模型输出无法解析 |

`exit_code` 只给 CLI 用：`main()` 捕获后 `print` 到 stderr 并 `return e.exit_code`。
库代码里一个 `print` 都没有 —— 日志策略交给调用方。

### 11.4 批量：线程池就够

这是纯 I/O 等待（每次 1.5–3.5 s，CPU 几乎不占），`ThreadPoolExecutor` 直接上；
`flash` 并发上限 2500，一般场景不用限流。缓存写入是「临时文件 + `os.replace`」，
并发调用不会读到半个文件。

```python
import concurrent.futures as cf
from summarize import summarize_file

def one(p):
    return p.name, summarize_file(p, "video_summary", cache=True)

with cf.ThreadPoolExecutor(max_workers=8) as pool:
    for name, data in pool.map(one, files):
        print(name, data["brief"])
```

完整的可运行示例见 `example_lib.py`（四段：基本用法 / 完整结果 / 错误处理 / 批量）。

### 11.5 与重构前的行为差异

| 项 | 旧 | 现 |
|---|---|---|
| 空输入 | `argparse` 报错，退出码 2 | `InputError`，退出码 1（与文档约定一致） |
| 缺 API Key | `[配置错误]` | `[输入错误] 未找到 API Key：…`（消息里带怎么配） |
| 文件编码 | `utf-8` + `errors="replace"`（静默乱码） | 自动识别 utf-8-sig → gb18030，都不行才报错 |
| 压缩重试失败 | print 到 stderr | 收进 `meta.warnings`（库调用不该往 stderr 写） |
| 缓存写入 | 直接覆盖 | 临时文件 + 原子替换 |

CLI 的退出码契约（0/1/2）与 `--json` / 缓存文件结构保持不变，旧缓存可直接复用。

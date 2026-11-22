# paper-radar 执行手册（给执行 Agent 的交接文档）

> 生成时间：2026-10-24 22:27
> 适用对象：接手实现的 Agent（人或 AI 均可）
> 前置文档：本文档**不重复**规格与计划的内容，只规定"怎么干、谁来干、什么算干完"

---

## 1. 你的身份与边界

**你是实现者，不是设计者。**

| 允许 | 禁止 |
|---|---|
| 按规格写代码 | 改 `docs/specs/` 里的任何设计决定 |
| 在规格留白处做小的实现选择（变量名、内部函数拆分） | 新增规格里没有的功能（"顺便加个缓存"） |
| 发现规格矛盾时**停下来上报** | 自己挑一个解释继续做 |
| 优化实现方式（不改外部行为） | 改接口签名、字段名、占位符名 |

**判断标准**：改动会不会让 `docs/specs/2026-10-24-paper-radar-design.md` 里的某一句变成假话？会 → 必须上报，不许自己改。

---

## 2. 开工前必读（按顺序，读完就停）

| 顺序 | 文件 | 读法 | 为什么 |
|---|---|---|---|
| 1 | `docs/specs/2026-10-24-paper-radar-design.md` | **全文精读** | 唯一的权威设计。字段、接口、错误分支都以它为准 |
| 2 | `docs/plans/2026-10-24-paper-radar-implementation.md` | **全文精读** | 任务分解、验收命令、卡点 |
| 3 | `docs/reviews/2026-10-24-plan-review.md` | 通读 | 知道哪些坑已经被修过，别再踩一遍 |
| 4 | `config.yaml` + `config.py` + `models.py` | 读代码 | 已有的两个模块，接口必须对齐 |
| 5 | `docs/decisions-paper-radar.md` | **跳读** | 只在想质疑某个设计时才查理由 |

**不要读**：`.tmp/`（调研脚本，已废弃）、`logs/`、`outbox/`。

**上下文预算**：不要一次把全项目读进上下文。每个任务只需要读它涉及的文件 + 上游模块的接口（函数签名），不需要读上游实现。

---

## 3. 当前进度（交接时的真实状态）

### 已完成

| 项 | 文件 | 状态 |
|---|---|---|
| 目录骨架 | `sources/` `filters/` `summarize/` `render/` `publish/` `sinks/` `prompts/` `templates/` `data/` `logs/` `outbox/` `tests/fixtures/` | ✅ 全部就位，六个包有 `__init__.py` |
| 依赖清单 | `requirements.txt` | ✅ requests / PyYAML / pytest |
| 忽略规则 | `.gitignore` | ✅ |
| 配置 | `config.yaml` | ✅ 全字段，`qq.group_id` 仍为 `0`（占位，等用户给） |
| 配置加载 | `config.py` | ✅ 含必填校验、`public_url` 斜杠校验、环境变量取 key |
| 数据模型 | `models.py` | ✅ `Paper` 含 `primary_category`、`short_title()`、`authors_str()` |

### 未完成

| 任务 | 文件 | 状态 |
|---|---|---|
| T0 剩余 | 虚拟环境 `.venv`、装依赖 | ❌ 未做 |
| T1 站点仓库 | GitHub 仓库 + Pages | ❌ **被阻塞**：GitHub MCP 只有读权限，建仓返回 403 |
| T2 剩余 | `store.py`、`log_util.py` | ❌ 未写 |
| T3–T12 | 见计划 | ❌ 未开始 |
| 模板 | `templates/qq.txt`、`templates/daily.html` | ❌ **等用户提供** |
| prompts | `prompts/pick.txt`、`prompts/write.txt` | ❌ 未写（内容可先按计划写默认版） |

**接手的第一个动作**：在项目根执行 `python -m venv .venv` 并装依赖，然后跑第 7 节的"门禁 0"。

---

## 4. 工作原则（执行者自己怎么干）

### 4.1 一次只推进一个任务

计划里的 T0–T12 有严格依赖。**不要同时改两个模块**，否则验收失败时无法定位是哪边的错。

### 4.2 验收门禁：跑不通不许进下一步

每个任务末尾都有验收命令。规则：

- 命令必须**真的跑一遍**，把输出贴进你的进度汇报。
- 输出不符合预期 → 修当前任务，不要带着问题往下走。
- 验收命令本身写错了（比如路径不对）→ 可以修命令，但要说明为什么。

**"我觉得应该没问题"不算通过。**

### 4.3 不许做的五件事

1. 不许改 `docs/` 下任何文件（那是设计与决策记录，只读）。
2. 不许把 `config.yaml` 里的值硬编码进代码。
3. 不许在 `print` 里输出 `▍`、`【】` 这类字符到 Windows 控制台（会 `UnicodeEncodeError`）—— 除了 `main.py` 里已 `reconfigure(encoding="utf-8")` 之后。
4. 不许用 `str.format` 渲染模板（CSS 的 `{}` 会炸），只能用 `str.replace`。
5. 不许为了"跑通"而 mock 掉真实依赖后宣称完成 —— mock 只允许出现在 `tests/` 里。

### 4.4 必须停下来问用户的情况

| 情况 | 为什么必须问 |
|---|---|
| 需要 `qq.group_id` | 只有用户知道 |
| 需要 GitHub 仓库 / Pages 地址 | MCP 权限不足，只能用户建 |
| 需要 LLM API Key | 环境变量，只有用户能设 |
| 规格与计划冲突 | 说明设计有问题，不能自己裁决 |
| 某个验收连续 2 次不通过且原因不明 | 继续试是浪费，先上报现象 |
| 想改任何接口签名 | 会影响上下游已完成的模块 |

### 4.5 失败处理

同一个验收失败 **2 次** 就停。向用户报告：

```
任务：T3 采集
验收命令：xxx
实际输出：xxx（贴原文）
已尝试：1) … 2) …
我的判断：可能是 xxx
需要你决定：xxx
```

不要无限重试，不要把错误吞掉改成 `try/except: pass`。

---

## 5. 子代理编排原则（如果你要派子代理）

> 适用于"主 Agent 派子 Agent 干活"的场景。若你独自顺序执行，可跳过本节。

### 5.1 派活的粒度

**一个子代理只领一个任务（T 级），不领"实现半个项目"。**

理由：子代理没有全局上下文，任务越大越容易自由发挥，产出越难验收。给它 T8（渲染），不要给它"把输出链路做完"。

### 5.2 prompt 必须自包含

子代理看不到你的上下文。给它的 prompt 必须包含五样东西：

```
1. 目标：要实现哪个任务，对应规格的哪一节
2. 输入：要读哪几个文件的哪些函数（给绝对路径）
3. 产出：要创建/修改哪些文件（给绝对路径）
4. 验收：跑什么命令，期望看到什么
5. 禁止：不许改 docs/、不许改接口、不许新增功能
```

**反面例子**（别这么写）：
> "帮我实现渲染模块"

**正面例子**：
> "实现 `render/text.py` 的 `render(papers_by_domain, date, public_url, cfg) -> str`。
> 规格见 `docs/specs/...` 第 8.1 节（QQ 消息模板）与第 9 节（降级渲染）。
> 输入是 `dict[str, list[Paper]]`，Paper 定义见 `models.py`。
> 产出文件：`C:/Users/guff/Desktop/search the paper/render/text.py`。
> 验收：`python -m render.text` 打印出含 9 条、每条带锚点链接的文本。
> 禁止改 docs/、禁止改 Paper 字段、禁止加规格外的排版。"

### 5.3 子代理不许改的东西

- `docs/` 全部（只读）
- 已通过验收的模块的**接口签名**（内部实现可改）
- `config.yaml` 的字段名

发现需要改 → 子代理停下来上报，由主 Agent 决定。

### 5.4 主 Agent 必须亲自验收

**不要相信子代理说"已完成"。** 它可能：
- 只写了函数没跑
- 跑了但输出不对
- 改了别的文件让测试通过

主 Agent 的动作：
1. `ls` 确认文件真的存在
2. 亲自跑验收命令
3. 抽查关键逻辑（比如 `id` 有没有剥 `vN`）

### 5.5 并行只在无共享文件时用

| 可以并行 | 不可以并行 |
|---|---|
| T3 采集 ∥ T5 LLM 客户端（不同文件、不同包） | T6 精选 ∥ T7 总结（都改 `summarize/`，且 T7 依赖 T6 的产出） |
| T9 发布 ∥ T10 推送（都只吃字符串） | 任何两个任务同时改 `main.py` |
| T1 仓库准备 ∥ 任何代码任务 | 两个任务同时改 `models.py` |

**判定方法**：两个任务要写的文件集合有交集 → 必须串行。

### 5.6 交接物用固定格式

每个子代理完成后，必须回一份这样的东西（主 Agent 据此判断能否进下一任务）：

```
任务：T6 精选
产出文件：
  - summarize/pick.py
  - prompts/pick.txt
验收命令：python -m summarize.pick
验收输出：（贴真实输出，含三个领域各 3 条的 id 和 reason）
已知问题：
  - 模型偶尔返回 2 条，补位逻辑已覆盖（见 tests/test_pick_fallback.py）
未做：
  - 无
```

### 5.7 最多两层

主 Agent → 子 Agent。**不要子代理再派子代理**，否则上下文丢失，验收链断裂。

---

## 6. 分工方案

### 6.1 推荐：单 Agent 顺序执行

项目总量约 500 行代码，13 个任务。单 Agent 顺序做最稳，因为：

- 上下文连续，不用反复解释背景
- 出错时定位简单
- 不需要写交接文档

**只有在以下情况才拆子代理**：单个任务特别大（如 T8 渲染含两个模板）、或需要并行压缩时间。

### 6.2 需要拆时：按阶段分，不按文件分

| 阶段 | Agent | 任务 | 前置条件 | 交接物 |
|---|---|---|---|---|
| **P0** | Agent-Setup | T0 剩余（venv+依赖） | 无 | 门禁 0 通过 |
| **P0 并行** | Agent-Repo | T1 仓库 + Pages（**需人工**） | 用户提供 GitHub 操作 | `curl` 拿到 200 |
| **P1** | Agent-Core | T2 剩余（store / log_util）+ T3 采集 + T4 判定 | P0 通过 | M1 验收输出 |
| **P1 并行** | Agent-LLM | T5 客户端（只依赖 config） | P0 通过 | 一次真实 chat 成功 |
| **P2** | Agent-Pick | T6 精选 + 补位测试 | P1 的 T4、T5 都完成 | 每领域 3 条带 reason |
| **P3** | Agent-Write | T7 总结 | P2 完成 | `llm_ok=True` ≥7 篇 |
| **P4** | Agent-Render | T8 渲染（**需模板**） | P3 完成 + 模板到手 | 本地打开 HTML 见 9 卡片 |
| **P5 并行** | Agent-Publish | T9 发布 | P4 完成 | 公网链接可打开 |
| **P5 并行** | Agent-Push | T10 推送（**需群号**） | P4 完成 + 群号 | 群里收到消息 |
| **P6** | Agent-Wire | T11 编排 + 定时 | P5 全部完成 | 计划任务触发成功 |
| **P6** | Agent-Test | T12 测试 | 各模块完成 | `pytest` 5 passed |

**注意**：P5 的两个任务是唯一真正可以并行的（T9 只碰 `publish/`，T10 只碰 `sinks/`）。其余"并行"都是指与主线不同文件的任务错开跑。

### 6.3 子代理 prompt 模板

```
你是 paper-radar 项目的实现者。只做下面这一件事，不要扩大范围。

【任务】{T编号} {任务名}

【必读】
- 规格：{绝对路径} 第 {x} 节
- 计划：{绝对路径} 第 {x} 节
- 上游接口：{文件路径}（只读需要的函数签名）

【要做的事】
1. …（具体到函数名和参数）
2. …

【产出文件】
- {绝对路径}

【验收】
命令：{可执行命令}
期望：{可证伪的具体输出}

【禁止】
- 改 docs/ 下任何文件
- 改已存在的接口签名
- 新增规格外的功能
- 用 try/except 吞掉错误

【完成后回报】
任务编号 / 产出文件 / 验收命令的真实输出 / 已知问题 / 未完成项
```

---

## 7. 验收门禁表

按顺序过，**前一个不通过不许做下一个**。

| 门禁 | 对应任务 | 命令 | 通过标准 |
|---|---|---|---|
| G0 | T0 | `python -c "import requests, yaml, pytest"` + key 检查 | 两条命令退出码均为 0 |
| G1 | T1 | `curl.exe -s -o NUL -w "%{http_code}" {public_url}test.html` | 返回 `200` |
| G2 | T2 | `python -m config` | 打印领域顺序、篇数、db 路径、Pages 地址 |
| G3 | T3 | `python -m sources.arxiv` | 三领域均非零；最旧发布时间距今 ≤72h |
| G4 | T4 | 计划 §5 的断言脚本 | `domain ok`，且 aerospace < embodied |
| G5 | T5 | 一次真实 chat 调用 | 返回非空文本，打印 token 用量 |
| G6 | T6 | `python -m summarize.pick` | 每领域 3 条，id 都在候选集内 |
| G7 | T7 | `python -m summarize.write` | `llm_ok=True` ≥ 7/9，tldr 长度 60–100 |
| G8 | T8 | `python -m render.html --out outbox\preview-{date}.html` | 9 个卡片；`llm_ok=False` 显示降级文案 |
| G9 | T9 | 浏览器打开 `{public_url}daily-{date}.html` | 200 且内容正确 |
| G10 | T10 | 手工调 `send_group` | 群里收到测试消息 |
| G11 | T11 | `--dry-run` → `--ignore-history --dry-run` → 空数据 → 真发 | 四步各自符合预期（见计划 §12） |
| G12 | T12 | `pytest tests -q` | 5 passed |

---

## 8. 阻塞项（必须等用户，不要硬做）

| 项 | 阻塞任务 | 缺它会发生什么 |
|---|---|---|
| `qq.group_id` | T10、T11 | 无法发群消息 |
| GitHub 仓库 + Pages 配置 | T1、T9 | 无公网链接；MCP 建仓 403 |
| `DASHSCOPE_API_KEY` | T5 起 | 所有 LLM 调用 401 |
| `templates/qq.txt` | T8 | QQ 文案只能用占位版 |
| `templates/daily.html` | T8 | 网页只能用占位版 |
| 阿里云 ECS 的 SSH 信息（系统/地区） | T13（v1.1） | 无法部署，但不影响 v1 |

**处理方式**：缺项时先做不依赖它的任务，把阻塞项集中列给用户，不要自己造一个假值（假的 `group_id` 会让验收误通过）。

---

## 9. 恢复执行的方法

如果上下文丢失或换人接手，按这三步恢复：

1. `ls -1 *.py *.yaml` + `find . -name "*.py" -not -path "./.venv/*"` 看实际有哪些文件
2. 对照第 3 节的进度表，找出**第一个未完成的任务**
3. 跑该任务前一个门禁命令，确认上游仍然可用，然后从那里继续

**不要重做已完成的文件**，除非门禁跑不过。

---

## 10. 交付标准

v1 算完成，必须同时满足：

- [ ] G0–G12 全部通过，输出留档
- [ ] `python main.py` 能发出一条真实的日报到 QQ 群
- [ ] 手机点开消息里的链接，能看到 9 篇详细解读
- [ ] 第二天再跑，不会重复推送同一篇论文
- [ ] 周末跑，群里安静且不发空日报
- [ ] `logs/run.log` 有一次完整的成功记录
- [ ] `pytest tests -q` 全绿

---

## 附：当前代码接口（供对齐，勿改）

```python
# config.py
load(path: str = "config.yaml") -> dict        # 校验必填、取 env key、填 run 默认值
domain_names(cfg: dict) -> list[str]           # 领域顺序 = 渲染顺序

# models.py
@dataclass
class Paper:
    id, title, abstract, authors, categories, primary_category,
    published, date, comment, abs_url, pdf_url,
    domain, score, picked_reason, tldr, detail, llm_ok
    short_title(n=40) -> str
    authors_str(n=3) -> str
```

**尚未定义、由后续任务补齐的接口**（见计划各节）：
`store.init/filter_unpushed/mark_pushed`、`sources.arxiv.fetch_all`、`filters.domain.assign_domain`、
`filters.rank.top_n`、`summarize.client.chat/chat_json`、`summarize.pick.pick`、
`summarize.write.write_all`、`render.text.render`、`render.html.render`、
`publish.pages.publish`、`sinks.qq.send_group`。

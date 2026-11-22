# paper-radar 设计规格（v1）

> 日期：2026-10-24
> 状态：**待批准**
> 目标读者：项目作者本人（大一，C++ 已学到函数章，Python 能读懂但未系统学过）
> 修订：v2，已吸收独立复核提出的 14 项问题

---

## 1. 这个程序做什么

每天早上自动去 arXiv 抓三个领域的最新论文，用大模型给每篇写一句人话总结，把摘要发到 QQ 群，同时给一个公网链接，点开能看到每篇的详细解读。

**一句话**：把"每天花两小时刷 arXiv"压缩成"早上扫五分钟"。

### v1 做

- 抓 3 个领域，**每领域 3 篇，共 9 篇**
- 每篇一句 100 字以内中文总结，结论先行
- 生成单文件 HTML（内联样式，不依赖 CDN），含每篇 300–500 字详细解读
- HTML 发到 GitHub Pages，得到公网链接
- 推送到指定 QQ 群：**一条纯文本消息发完**，每篇附一个指向该篇详细解读的链接
- 每天早上 7:30 自动跑
- 已推送过的论文不重复推

### v1 不做（明确排除）

| 不做 | 为什么 |
|---|---|
| 图形化配置后台 | 配置项还没稳定，先做 UI 必返工 |
| 多种语言风格切换 | 每多一种风格多一层抽象，v1 只写死"结论先行+术语解释" |
| 向量检索 / 语义排序 | 关键词粗筛 + LLM 精选已经够，向量是 v2 |
| 顶会录用白名单 | arXiv comment 字段已覆盖 12% |
| 邮件 / 微信 / 飞书推送 | 抽屉式设计，加一个文件即可，不属于 v1 |
| 论文问答 | 独立子项目 |
| 并发调用 LLM | 15 次串行约 2 分钟，在预算内；并发的线程异常对新手是灾难 |
| 页面上的"往期完整列表" | 静态站不能列目录，v1 只放"上一期"单链 |

---

## 2. 整体架构

一条直线，每个盒子只跟邻居说话。

```
config.yaml
     │
     ▼
 [采集] sources/arxiv.py ──► list[Paper]（原始）
     │
     ▼
 [筛选] filters/domain.py + rank.py ──► 打领域标签、粗筛到每领域 30 篇
     │
     ▼
 [精选] summarize/pick.py ──► 模型挑出每领域 quota 篇（v1 = 3）
     │
     ▼
 [总结] summarize/write.py ──► 每篇填上 tldr(100字) + detail(500字)
     │
     ├──► [发布] publish/pages.py ──► git push ──► 公网固定链接
     │                                                    │
     ▼                                                    ▼
 [投递] sinks/qq.py    ──► 发群消息（文本 + 上面那个链接）
     │
     ▼
 [记账] store.py       ──► SQLite：记下这一批发成功的 ID
```

**为什么要分开？** 每个文件都能单独跑、单独测。改筛选规则只动 `filters/`，换推送渠道只写一个新的 `sinks/xxx.py`。这就是"可拓展"——不是靠框架，是靠**每个部件的输入输出格式固定下来**。

### 目录结构

```
search the paper/
├── config.yaml              # 所有可调参数（格式见 §3）
├── requirements.txt         # 只有 requests + PyYAML
├── main.py                  # 编排，约 90 行
├── models.py                # Paper 数据结构
├── store.py                 # SQLite：已推送记录
├── sources/
│   └── arxiv.py             # 抓取 + 解析 atom → list[Paper]
├── filters/
│   ├── domain.py            # 判断论文属于哪个领域
│   └── rank.py              # 关键词打分，粗筛到 30 篇
├── summarize/
│   ├── client.py            # 极简 LLM 调用（requests + JSON）
│   ├── pick.py              # 精选 quota 篇（v1=3）
│   └── write.py             # 写 tldr + detail
├── render/
│   ├── text.py              # QQ 推送用的纯文本
│   └── html.py              # 单文件 HTML
├── publish/
│   └── pages.py             # 写入站点目录 + git commit/push
├── sinks/
│   └── qq.py                # NapCat OneBot 11：发群消息
├── templates/
│   └── daily.html           # 骨架，占位符是 {{KEY}}
├── logs/                    # 运行日志（自动创建）
├── outbox/                  # 发送失败时存文本（自动创建）
└── tests/
    ├── test_domain.py
    ├── test_rank.py
    ├── test_dedup.py
    └── fixtures/sample_arxiv.xml
```

**依赖只用两个**：`requests`（发 HTTP）、`PyYAML`（读配置）。XML 用标准库 `xml.etree.ElementTree` 解析，不装 lxml。LLM 用 `requests` 直接 POST，不用 openai SDK —— 你能亲眼看到请求长什么样。

---

## 3. 配置契约（config.yaml 全文）

**这是全篇最重要的部分**。所有模块只从这里取参数，代码里不写死任何数字。

```yaml
# ========== 必填 ==========
llm:
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen-plus"
  api_key_env: "DASHSCOPE_API_KEY"   # 只写环境变量名，key 本身不落文件

qq:
  api_base: "http://127.0.0.1:3000"  # NapCat 的 OneBot HTTP 服务地址
  group_id: 123456789                # 必须是整数
  access_token: ""                   # NapCat 没设 token 就留空

publish:
  repo_dir: "C:/Users/guff/paper-radar-site"   # 站点仓库的本地路径
  site_dir: "docs"                             # 相对 repo_dir 的产物目录
  public_url: "https://YOURNAME.github.io/paper-radar/"
  branch: "main"

# ========== 可选（有默认值） ==========
run:
  window_hours: 72          # 采集窗口，见 §5
  per_category_limit: 100   # 每个 arXiv 分类取多少条
  timeout_sec: 40
  retries: 3
  request_interval: 3.0     # 两次 arXiv 请求的间隔（秒）
  max_message_chars: 3800   # 单条 QQ 消息字符上限，超了自动分条

domains:
  computer:
    name: 计算机
    categories: [cs.AI, cs.LG, cs.CV, cs.CL]
    keywords: [transformer, diffusion, LLM, pretrain, benchmark, agent]
    quota: 3
  embodied:
    name: 具身智能
    categories: [cs.RO]
    keywords: [manipulation, VLA, embodied, sim2real, locomotion,
               dexterous, policy learning, imitation]
    quota: 3
  aerospace:
    name: 飞行器
    categories: [cs.RO, eess.SY, physics.flu-dyn]
    keywords: [UAV, drone, aerial, flight, aero, wing, rotor,
               trajectory, guidance, aerodynamic]
    quota: 3
```

> `quota` 是每领域最终送几篇。v1 定为 3（一天 9 篇），改动这一个数字即可调整总量，代码不用动。

### 字段对照表

| 键 | 类型 | 必填 | 默认 | 谁读 |
|---|---|---|---|---|
| `llm.base_url` | str | ✅ | — | `summarize/client.py` |
| `llm.model` | str | ✅ | — | `summarize/client.py` |
| `llm.api_key_env` | str | ✅ | — | `main.py`（启动时 `os.environ` 取值） |
| `qq.api_base` / `group_id` | str / int | ✅ | — | `sinks/qq.py` |
| `qq.access_token` | str | ❌ | `""` | `sinks/qq.py` |
| `publish.repo_dir` / `site_dir` | str | ✅ | — | `publish/pages.py` |
| `publish.public_url` | str | ✅ | — | `render/text.py` |
| `publish.branch` | str | ❌ | `main` | `publish/pages.py` |
| `run.*` | int/float | ❌ | 见上 | `sources/arxiv.py` / `main.py` |
| `domains` | dict | ✅ | — | `filters/domain.py` / `render/*` |

**启动自检**：`main.py` 第一件事是校验必填项，缺任何一项立刻打印缺哪个键并退出，不允许跑到一半才炸。

**密钥不写进 yaml**：`llm.api_key_env` 存的是环境变量名。你需要在系统环境变量里设 `DASHSCOPE_API_KEY`。理由：配置文件可能被截图、被提交到 git，key 一旦泄露要重新申请。

---

## 4. 数据模型

整个程序里流动的只有一种东西：`Paper`。

```python
@dataclass
class Paper:
    id: str              # 裸 ID "2610.31670"，已去掉 v1/v2 后缀 ← 去重主键
    title: str
    abstract: str        # 已去掉换行
    authors: list[str]
    categories: list[str]
    published: datetime  # 完整时间戳（UTC），用于窗口过滤与排序
    date: str            # "2026-10-22"，用于展示和文件名
    comment: str         # arXiv comment 字段，常含"Accepted at CoRL 2026"
    abs_url: str         # https://arxiv.org/abs/2610.31670v1（保留原始版本号）
    pdf_url: str
    domain: str = ""     # computer / embodied / aerospace，筛选阶段才填
    score: float = 0.0
    picked_reason: str = ""  # 精选阶段模型给的理由
    tldr: str = ""       # ≤100 字
    detail: str = ""     # 300–500 字
    llm_ok: bool = False
```

**三个关键约定**：

1. **`id` 存裸 ID**。arXiv 返回的是 `2610.31670v1`，入库前必须剥掉 `vN`。否则同一篇论文升级到 v2 时 id 变了，去重失效，会被当成新论文重推。`abs_url` 里保留原始带版本号的地址。
2. **`published` 存完整时间戳**，不是日期字符串。否则无法计算 72 小时窗口，也无法在一天内排序。
3. **`date` 单独存**。展示和文件名用它，不要从 datetime 现场格式化（省得到处写 strftime）。

**为什么用 dataclass 而不是字典？** 字典拼错键名不报错，只会静默拿到 `None`，你要 debug 半天。dataclass 写错字段名，Python 当场报错。

---

## 5. 采集规则

### 5.1 参数与口径

| 项 | 值 |
|---|---|
| 请求方式 | 每个 arXiv 分类单独一次请求 |
| 每分类条数 | `max_results=100`（`run.per_category_limit`） |
| 请求间隔 | ≥3 秒（`run.request_interval`），arXiv 官方要求 |
| 本地过滤 | 只保留 `published` 在 `window_hours`（默认 72 小时）内的 |
| 代理 | **直连，不走系统代理**（实测直连 200，走代理会 502） |
| 重试 | 3 次，间隔 2/4/8 秒 |

**为什么窗口是 72 小时而不是"昨天"**：实测 2026-10-24 查询时，arXiv 最新发布日期只到 10-22 —— 索引有约 1 天延迟。写死"抓昨天"会周期性漏数据。取 3 天窗口 + 去重，多抓的部分会被 SQLite 挡掉。

**窗口是容错，不是全覆盖**：cs.AI 日产量数百，100 条只覆盖半天。这是有意的 —— 要的是"最新"，不是"全量"。

### 5.2 请求 URL 示例

```
https://export.arxiv.org/api/query
  ?search_query=cat:cs.RO
  &start=0
  &max_results=100
  &sortBy=submittedDate
  &sortOrder=descending
```

注意：**不在 `search_query` 里写日期范围**，日期在本地过滤。原因：`submittedDate` 的区间语法对时区敏感，容易查空（实测带日期区间返回 0 条）。

### 5.3 atom 字段 → Paper 字段映射

| atom 节点 | 映射到 | 处理 |
|---|---|---|
| `<id>` | `id` / `abs_url` | 取 `/abs/` 之后的部分；`id` 去掉 `vN` 后缀 |
| `<title>` | `title` | 去掉换行，压缩连续空格 |
| `<summary>` | `abstract` | 去掉换行 |
| `<published>` | `published` / `date` | 解析 ISO 8601；`date` 取前 10 字符 |
| `<name>`（多个） | `authors` | 全部收进 list |
| `<category term="...">` | `categories` | 取所有 `term` 属性 |
| `<arxiv:comment>` | `comment` | 可能不存在，缺失则空串 |
| `/pdf/` 链接 | `pdf_url` | — |

**命名空间坑**：atom 的标签带命名空间（`{http://www.w3.org/2005/Atom}entry`）。用 `ElementTree` 时要么写完整命名空间，要么用 `findall("{*}entry")` 通配。这是新手最容易卡住的地方，规格里先写明白。

### 5.4 预期原始量

| 领域 | 分类数 | 去重后预计 |
|---|---|---|
| 计算机 | 4 | 250–350 篇（cs.AI/cs.LG 重叠严重） |
| 具身智能 | 1（cs.RO） | 50–100 篇 |
| 飞行器 | 3（含 cs.RO 重叠） | 40–90 篇 |

合计约 350–450 篇，最终只留 **9 篇** —— **筛掉 98%**。所以筛选才是这个产品的价值所在，抓取只是苦力活。

---

## 6. 领域判定

`cs.RO` 同时属于 `embodied` 和 `aerospace`，一篇讲无人机抓取的论文两个领域都想要。

**规则（严格按顺序）**：

1. 若论文的分类**只**出现在一个领域的 `categories` 里 → 直接归该领域，结束。
2. 若出现在多个领域（即 cs.RO 冲突），看 `aerospace` 关键词是否命中**标题** → 是则归飞行器，结束。
3. 否则看 `embodied` 关键词是否命中标题 → 是则归具身，结束。
4. 都不命中 → 按 `config.yaml` 中 `domains` 的**书写顺序**，归第一个包含该论文主分类的领域。

**为什么规则 1 优先**：不先判"是否冲突"，一篇 cs.CV 的无人机检测论文标题含 UAV 就会被规则 2 抓走，从计算机池里消失。冲突消解只对真正跨领域的分类生效。

**为什么标题权重高于摘要**：标题是作者浓缩的，摘要里常有"we compare with drone dataset"这类顺带提及，容易误判。

**一篇论文只能进一个领域，不允许重复出现在两栏。**

---

## 7. 筛选与总结（三段式）

这里是产品最值钱的地方。抓 400 篇不难，**从 400 篇里选出对的那 3 篇**很难。

### 7.1 第一段：关键词粗筛（免费）

```
score = 标题命中关键词数 × 3
      + 摘要命中关键词数 × 1
      + comment 含 "accepted/published/to appear" × 5
```

按 score 降序取前 30 篇。只求"不漏掉明显相关的"，不追求精度。

**匹配规则**：关键词匹配**大小写不敏感**（全部转小写后比对），按"标题/摘要里出现了几个不同关键词"计数，同一关键词出现多次只算一次。

### 7.2 第二段：LLM 精选（每领域一次调用）

把 30 篇的**标题 + 摘要前 200 个字符**拼成清单，让模型选出 `quota` 篇（v1 为 3 篇）并给理由。

返回格式：
```json
{"picked": [{"id": "2610.31670", "reason": "首次在真机上验证了……"}]}
```

- 输入约 6000 tokens，单次成本几分钱
- 比关键词靠谱：关键词只会数命中，模型能判断"这篇是不是增量灌水"
- **为什么值得多花这一次调用**：一个领域一天只推 3 篇，选错了这个方向今天就等于没看

**必须校验**：`picked` 里的 id 必须在候选集里；不在的丢弃。若有效结果不足 `quota`，用粗筛分数顺位补足。

### 7.3 第三段：逐篇写总结

对每篇一次调用，返回：
```json
{
  "tldr": "≤100字中文，结论先行，第一句说清这篇做成了什么",
  "detail": "300-500字，分四段：做了什么 / 怎么做的 / 结果如何 / 为什么值得看"
}
```

**风格约束（写进 prompt）**：
- 第一句必须回答"解决了什么问题、做到了什么程度"
- 术语首次出现跟一句白话解释，例：`VLA（把视觉输入直接变成机器人动作的模型）`
- 禁止"本文提出了一种新颖的方法"这类空话
- 数字必须保留（提升多少、在什么数据集上）

**执行方式**：**串行**，逐篇调用，每次约 5–10 秒，9 篇约 90 秒。单篇失败重试 1 次，仍失败标记 `llm_ok=False`，继续下一篇。

**成本**：3 次精选 + 9 次写作 = 12 次/天，单日成本一两毛钱。

---

## 8. 渲染规则

### 8.1 QQ 文本消息

**一条消息发完**，每篇论文带一个指向自己详细解读的链接：

```
【论文日报 2026-10-24】

▍计算机
标题（超过 40 字截断）
一句话总结，100 字以内，结论先行……
详细解读 → {public_url}daily-2026-10-24.html#2610.31670

▍具身智能
标题
总结……
详细解读 → ...#2610.31520

▍飞行器
标题
总结……
详细解读 → ...#2610.31400
```

**四条硬规则**：

1. 三个领域固定顺序：计算机 → 具身智能 → 飞行器（按 `config.domains` 书写顺序）
2. **链接带日期 + 锚点**，不是首页地址。原因：如果指向 `index.html`，第二天首页换成新一期，昨天消息里的链接就会跳到"同一位置但完全不同的论文"，历史消息全部失效。带日期 + 锚点的链接**永久指向那一天的那一篇**。
3. 链接必须带 `https://`，否则 QQ 不识别为可点击
4. 域名从 `config.publish.public_url` 读，不硬编码

**长度**：9 篇 ×（标题 40 + 总结 100 + 链接 90 + 标签）≈ 2000 字符，**一条消息发完，仍在 QQ 4200 字符上限内**。
`run.max_message_chars`（默认 3800）保留为保险：若你把 `quota` 调大导致超长，自动按领域分条，每条标「(1/2)」。

**降级渲染**：
- 某领域抓取失败 → 该节写一行「本领域今日抓取失败」
- 某篇 `llm_ok=False` → 该条写「总结生成失败，点链接看原文」

### 8.2 HTML（发布到 Pages）

- 单文件，CSS 内联，不依赖任何 CDN
- 结构：标题 → 三个领域分节 → 每篇一个卡片
- **每个卡片带 `id="{paper.id}"`**，这样锚点链接 `#2610.31670` 能直接跳到那一篇
- 卡片内容：标题 / 作者 / 录用信息（若有）/ 100 字总结 / 详细解读 / 原文链接
- 底部「上一期」单链（v1 不做完整往期列表 —— 静态站无法自己列目录）
- 模板块占位符统一用 `{{KEY}}`，用 `str.replace` 渲染（不要用 `str.format`，会和 CSS 里的 `{}` 打架）
- **每天只生成一个文件**：`daily-YYYY-MM-DD.html`。不生成 `index.html` —— 没有它反而更简单，链接也不会因为"首页更新"而失效。
- 文件写入必须显式 `encoding="utf-8"`

---

## 9. 发布与投递

### 9.1 一次性准备（只做一次）

1. 建一个公开 GitHub 仓库（如 `paper-radar-site`）
2. Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`，目录 `/docs`
3. 本地 clone 到 `publish.repo_dir`
4. 首次 push 一个占位文件（如 `docs/test.html`），用 curl 确认返回 200
5. 把站点根地址填进 `config.yaml` 的 `publish.public_url`，**结尾必须带斜杠**（`https://YOURNAME.github.io/paper-radar/`），代码会直接拼 `daily-2026-10-24.html#id`

**站点目录与项目文档分开**：站点仓库（`repo_dir`）是独立仓库，不是本项目目录。本项目的 `docs/` 只放设计文档，不会被公开。

**前提**：本机已装 git 并可免密 push（`git push` 不弹密码）。用 `subprocess` 调用 git 命令，失败时把 git 的 stderr 原样打进日志 —— 绝大多数 push 失败都是凭证问题，stderr 会直接告诉你原因。

### 9.2 每次发布

| 步骤 | 动作 |
|---|---|
| 1 | 写 `daily-YYYY-MM-DD.html` 到 `repo_dir/docs/`（**不生成 index.html**） |
| 2 | `git add -A && git commit -m "daily: 2026-10-24" && git push` |
| 3 | 等 60 秒（Pages 构建延迟） |
| 4 | 发 QQ 消息 |

**为什么不生成 index.html**：如果 QQ 消息里的链接指向首页，第二天首页换成新一期，昨天那条消息的链接就会跳到"同一位置但完全不同的论文"。带日期 + 锚点的链接永久有效，代价只是没有"最新一期"总入口 —— 而那个入口本来也没人用。

**顺序不能反**：Pages 有 30–60 秒构建延迟。先发消息后 push，群里点开是 404，看起来像程序坏了。

### 9.3 发到 QQ 群

NapCat OneBot 11，只用一个接口：

```
POST {qq.api_base}/send_group_msg
{"group_id": 123456789, "message": "..."}
```

若 `access_token` 非空，请求头加 `Authorization: Bearer {token}`。

v1 不用 `upload_group_file` —— 详细内容在网页里。

---

## 10. 错误处理

| 故障 | 处理 | 用户看到什么 |
|---|---|---|
| arXiv 超时 / 502 | 重试 3 次，仍失败则跳过该分类 | 「本领域今日抓取失败」，其余照发 |
| LLM 某篇失败 | 重试 1 次，仍失败标 `llm_ok=False` | 「总结生成失败，请直接看原文」+ 链接 |
| **LLM 返回非法 JSON / 字段缺失** | 重试 1 次；仍失败按 `llm_ok=False` | 同上 |
| **`picked` 里 id 不在候选集** | 丢弃该条，用粗筛分数补位 | 无感知 |
| LLM 全部失败 | 不发日报，写日志，群里发一条错误提示 | 「今日总结全部失败，请检查 API」 |
| git push 失败 | 重试 2 次；仍失败则**不发 QQ 消息** | 群里安静，本地留存 HTML |
| QQ 发送失败 | 重试 2 次，仍失败把文本写入 `outbox/YYYY-MM-DD.txt` | 无感知，可手动补发 |
| 今天没有新论文（周末） | **不发群消息**，只写日志，**不生成 HTML** | 群里安静，上一期页面仍可访问 |

**不更新 index.html 的原因**：周末把昨天的页面刷成空白页，比不发更糟。

---

## 11. 手动操作与调试

| 命令 | 行为 |
|---|---|
| `python main.py` | **正式全流程**：抓取 → 筛选 → 精选 → 总结 → 发布 → 推群 |
| `python main.py --dry-run` | 走完抓取/筛选/精选/总结，**跳过 Pages 发布和 QQ 推送**，把文本打印到终端并写本地 `outbox/preview-日期.html` |
| `python main.py --resend 2026-10-24` | 只重发 `outbox/2026-10-24.txt` 的内容，不重抓、不重新总结、不发布 |

`--dry-run` 会真实调用 LLM（否则打印出来全是空字段，看不出渲染对不对），但不对外产生任何副作用。**这是你改 prompt 时天天要用的开关。**

**Windows 计划任务**（每天 7:30）：

```
程序：C:\Users\guff\Desktop\search the paper\.venv\Scripts\python.exe
参数：main.py
起始于：C:\Users\guff\Desktop\search the paper
```

日志重定向到 `logs/run.log`，在代码里用 `logging.FileHandler(encoding="utf-8")` 实现，不依赖命令行重定向。

---

## 12. 编码与依赖约定

- **所有文件读写显式 `encoding="utf-8"`**。中文 Windows 控制台默认 GBK，直接 print `▍`、`【】` 这类字符有 `UnicodeEncodeError` 风险。
- 日志用 `logging`，`FileHandler(encoding="utf-8")`。
- 依赖只用两个：`requests`、`PyYAML`。XML 用标准库 `xml.etree.ElementTree`。
- LLM 用 `requests` 直接 POST，不引入 SDK —— 请求体看得见，出问题好排查。

---

## 13. 测试策略

| 层 | 测什么 | 怎么测 |
|---|---|---|
| 单元 | 领域判定（含 cs.RO 冲突的 4 种情形） | `tests/fixtures/sample_arxiv.xml` 喂进去，断言输出 |
| 单元 | 关键词打分排序 | 构造 5 篇假 Paper，断言取前 3 的顺序 |
| 单元 | **去重（v1/v2 同一篇）** | 同 ID 不同版本各一条，断言只留一条 |
| 集成 | 抓→筛→渲染 | mock 掉 LLM 与 QQ，断言文本含 9 条、HTML 含 9 个卡片 |
| 端到端 | 真发一次 | 先 `--dry-run` 看输出，再 `main.py` |

**测试的核心是去重和领域判定** —— 这两个错了，报错在很晚才显现（重复推送 / 某栏目长期空缺），肉眼很难发现。

---

## 14. 待定与假设

| 项 | 假设值 | 影响 |
|---|---|---|
| 每领域篇数 | 3 | 总 9 篇，一条消息发完，约 2000 字 |
| 推送时间 | 07:30 | 需笔记本开机；改为 Actions 则无此限制 |
| 定时方式 | Windows 计划任务 | 未确认你的机器日常在线时间 |
| 风格 | 单一样式 | v2 再做可切换 |
| `qq.group_id` | 待填 | 必须你提供 |
| `publish.repo_dir` / `public_url` | 待填 | 见 §9.1 一次性准备 |
| LLM 供应商 | 阿里云百炼 `qwen-plus` | 换 DeepSeek 只改 base_url 与 model |

---

## 15. 三个里程碑

| 里程碑 | 完成后你能看到 | 预计卡点 |
|---|---|---|
| **M1 采集** | 终端打印「共 380 篇，去重后：计算机 300 / 具身 62 / 飞行器 18」 | 领域判定的 cs.RO 冲突；XML 命名空间 |
| **M2 筛选+总结+渲染** | 终端打印「每领域选出 3 篇」，并生成一个能在浏览器打开的 HTML | prompt 调不出你要的语气；JSON 解析失败 |
| **M3 发布+推送** | QQ 群收到一条消息，手机点链接能打开详细解读 | Pages 首次配置；git 凭证 |

**M1 的验收不含"5/5/5"** —— 配额是 M2 精选阶段才产生的。M1 只证明"抓得到、分得对、去得了重"。

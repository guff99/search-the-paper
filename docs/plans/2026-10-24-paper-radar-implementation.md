# paper-radar 实施计划（v2）

> 依据：`docs/specs/2026-10-24-paper-radar-design.md`（v2）  
> 日期：2026-10-24  
> 规模：**每领域 3 篇，共 9 篇**，一条 QQ 消息发完（约 2000 字）  
> 修订：v2，已吸收独立评审的 6 项阻塞级 + 17 项重要级 + 8 项建议级意见  
> 状态：**待作者确认后开工**

---

## 0. 这份计划怎么用

1. 按 T0 → T12 顺序做，**每个任务做完先跑验收命令**，通过再进下一个。
2. 标了「可并行」的任务能同时做，其余严格串行。
3. 全篇命令统一用 PowerShell（Windows 默认）。若你用 Git Bash，把 `.venv\Scripts\` 换成 `.venv/Scripts/`。

**两处模板由作者提供**（本次不写死）：

| 文件                     | 内容            | 我提供什么        |
| ---------------------- | ------------- | ------------ |
| `templates/qq.txt`     | QQ 消息的整体文案与排版 | 占位符名 + 默认占位版 |
| `templates/daily.html` | 网页版式与样式       | 占位符名 + 默认占位版 |

**关于"替换模板不用改代码"的准确说法**：占位符名称（`{{date}}` / `{{sections}}` / `{{cards}}` / `{{prev_link}}`）是固定的，这四个不用动。但 `html.py` 里生成的卡片片段（`<article class="...">`）的 HTML 结构和 class 名必须和你模板里的 CSS 对齐，**模板到手后 `html.py` 可能要改 5–10 行**。这不是返工，是正常的对接成本。

---

## 1. T0 本地环境（约 40 分钟）

### 交付

目录骨架、`requirements.txt`、`config.yaml`、`.gitignore`、Python 虚拟环境

### 目录

```
search the paper/
├── config.yaml
├── requirements.txt
├── .gitignore
├── main.py
├── models.py
├── store.py
├── config.py
├── log_util.py
├── sources/__init__.py
├── filters/__init__.py
├── summarize/__init__.py
├── render/__init__.py
├── publish/__init__.py
├── sinks/__init__.py
├── prompts/
│   ├── pick.txt
│   └── write.txt
├── templates/
│   ├── qq.txt
│   └── daily.html
├── data/                  # SQLite 落这儿
├── logs/
├── outbox/
└── tests/
```

### `requirements.txt`

```
requests>=2.31
PyYAML>=6.0
pytest>=8.0
```

### 命令

```powershell
cd "search the paper"
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 配置

照规格 §3 抄 `config.yaml`，**新增一项**（规格漏了，评审指出）：

```yaml
store:
  db_path: "data/pushed.db"
```

填好 `qq.group_id`、`publish.repo_dir`、`publish.public_url`（**结尾必须带 `/`**）。

### API Key

**本项目不读 `.env`，key 只放系统环境变量。** 不要建 `.env`，不要装 `python-dotenv` —— 建了会以为代码会读，实际不会，然后花一晚上怀疑 key 错了。

```powershell
setx DASHSCOPE_API_KEY "sk-xxxx"
# 设完必须重开终端
```

`.gitignore`：

```
.venv/
__pycache__/
logs/
outbox/
*.db
data/
```

### 验收

```powershell
.venv\Scripts\python -c "import requests, yaml, pytest; print('deps ok')"

.venv\Scripts\python -c "import os,sys; k=os.environ.get('DASHSCOPE_API_KEY',''); print('key ok' if k else 'MISSING'); sys.exit(0 if k else 1)"
```

第二条**返回码非 0 就是没配好**。不要用 `echo %VAR%` —— 变量没设时它照样打印字面量、退出码 0，永远"通过"。

### 卡点

- `python` 命令不存在 → 改用 `py -3 -m venv .venv`
- `setx` 之后当前终端读不到 → 必须重开终端

---

## 2. T1 站点仓库与 Pages 准备（约 30 分钟，**可并行**）

> 评审指出这是最容易整段卡死、且卡住后前面全白做的地方，所以单独成任务、逐步验收。

| 步骤 | 动作                                                                      | 验收                                                                                                |
| -- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 1  | GitHub 建**公开**仓库，如 `paper-radar-site`                                   | 仓库页面能打开                                                                                           |
| 2  | Settings → Pages → Source 选 `Deploy from a branch`，分支 `main`，目录 `/docs` | 页面显示 "Your site is live at ..."                                                                   |
| 3  | `git clone <仓库地址> C:\Users\guff\paper-radar-site`                       | `git -C "C:\Users\guff\paper-radar-site" remote -v` 指向你的仓库                                        |
| 4  | 建 `docs/test.html`，随便写点内容，push                                          | `curl.exe -s -o NUL -w "%{http_code}" https://用户名.github.io/paper-radar-site/test.html` → **200** |
| 5  | 站点根地址填进 `config.yaml` 的 `publish.public_url`                            | 以 `/` 结尾                                                                                          |

**第 4 步拿到 200 之前不要进 T9。** Pages 的配置错误只有这一个地方能验证。

**路径要一致**：`public_url` 的路径段必须等于仓库名。仓库叫 `paper-radar-site`，地址就是 `https://用户名.github.io/paper-radar-site/`。写成 `paper-radar` 会 404，而 404 的排查提示（"等 60 秒"/"看 Source 配置"）会把你带到错误方向。

### 卡点

- push 要密码 → 配 SSH key，或用 `gh auth login`
- 200 拿不到 → 先看仓库 Actions 页签的 Pages 构建状态

---

## 3. T2 配置加载 + 数据模型 + 存储 + 日志（约 2 小时）

### 交付

`config.py`、`models.py`、`store.py`、`log_util.py`

### 做什么

**`config.py`** —— 唯一读 yaml 的地方。

```python
def load(path: str = "config.yaml") -> dict
    # 1) 读 yaml
    # 2) 校验必填：llm.base_url / llm.model / llm.api_key_env
    #              qq.api_base / qq.group_id
    #              publish.repo_dir / publish.site_dir / publish.public_url
    #              store.db_path
    # 3) 缺项 → print("缺少配置项: xxx"); sys.exit(1)
    # 4) 校验 public_url 以 "/" 结尾，不是则报错退出
    #    （少斜杠会拼出 https://x.github.iopaper-radar/daily-... 这种不可点链接，且不报错）
    # 5) 从 os.environ 取 api_key → cfg["llm"]["api_key"]；缺失也在这里 exit
    # 6) run.* 填默认值
```

**`models.py`** —— 比规格 §4 多一个字段（评审 B3）：

```python
@dataclass
class Paper:
    id: str                  # 裸 ID，已剥 vN
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    primary_category: str    # ← 新增：来自 <arxiv:primary_category>，规则 4 要用
    published: datetime
    date: str
    comment: str
    abs_url: str
    pdf_url: str
    domain: str = ""
    score: float = 0.0
    picked_reason: str = ""
    tldr: str = ""
    detail: str = ""
    llm_ok: bool = False

    def short_title(self, n: int = 40) -> str
```

**`store.py`** —— 返回连接，不是 None（评审 I13）：

```python
def init(path: str) -> sqlite3.Connection
    # 建目录、建表 pushed(id TEXT PRIMARY KEY, date TEXT, pushed_at TEXT)
    # 返回连接，全流程共用这一个

def filter_unpushed(conn, ids: list[str]) -> set[str]   # 返回"已推过"的 id 集合
def mark_pushed(conn, papers: list[Paper], date: str) -> None
```

**`log_util.py`**（评审 I2：原计划没人负责日志）：

```python
def setup() -> None
    # logging.basicConfig(
    #   level=INFO,
    #   format="%(asctime)s %(levelname)s %(message)s",
    #   handlers=[FileHandler("logs/run.log", encoding="utf-8"),
    #             StreamHandler(sys.stdout)])
```

`main.py` 第一行调它。计划任务跑失败时，`logs/run.log` 是唯一线索。

### 验收

```powershell
.venv\Scripts\python -c "from config import load; c=load(); print(c['domains']['computer']['quota'], c['store']['db_path'])"
# 期望：3 data/pushed.db

.venv\Scripts\python -c "import store; c=store.init('data/test.db'); print('db ok')"
```

### 卡点

- yaml 的 `group_id` 读出来是 int，OneBot 要求 int，**不要转 str**
- `data/` 不存在 → `init()` 里先 `os.makedirs(..., exist_ok=True)`

---

## 4. T3 采集（约 2 小时）

### 交付

`sources/arxiv.py`

### 做什么

```python
def fetch_category(category: str, run_cfg: dict) -> list[Paper]
    # 1) 拼 URL: https://export.arxiv.org/api/query
    #    ?search_query=cat:{category}&start=0&max_results={limit}
    #    &sortBy=submittedDate&sortOrder=descending
    # 2) requests.get(..., timeout=..., trust_env=False)   ← 绕开系统代理
    # 3) 重试 retries 次，间隔 2/4/8 秒
    # 4) _parse(xml)

def _parse(xml_text: str) -> list[Paper]
    # ElementTree.fromstring；用 findall("{*}entry") 通配命名空间

def filter_window(papers, hours) -> list[Paper]
    # ← 评审 B1：这一步原计划完全漏了，必须有
    # 保留 published >= now(UTC) - hours
    # 放在 _parse 之后、fetch_all 去重之前

def fetch_all(categories, run_cfg) -> list[Paper]
    # 逐分类 fetch_category → filter_window → 合并 → 按 id 去重
    # 每次请求之间 sleep(request_interval)
```

**四个解析坑**：

1. `<id>` 是 `http://arxiv.org/abs/2610.31670v1` → `id` 剥掉 `vN`，`abs_url` 保留完整
2. `<title>` / `<summary>` 有换行 → `re.sub(r"\s+", " ", t).strip()`
3. `<arxiv:primary_category term="cs.RO"/>` → 存进 `primary_category`（**不是** `categories[0]`，顺序不保证）
4. `<arxiv:comment>` 可能不存在 → 空串

文件末尾加：

```python
if __name__ == "__main__":
    # python -m sources.arxiv
    # 逐分类打印：抓取 N 条 → 窗口内 M 条；最后打印去重总数 + 最旧发布时间距今小时数
```

### 验收

```powershell
.venv\Scripts\python -m sources.arxiv
```

必须满足：

- 每个分类打印 `抓取 N / 窗口内 M`
- 最旧发布时间距现在 **≤ 72 小时**（可证伪）
- 去重后总数 > 100

### 卡点

- 周末照样有数据（72h 窗口覆盖到周四）。**连续性去重是 T11 接 store 之后才有的事，这一步不用管**
- 命名空间写错 → `findall("entry")` 返回空列表，这是第一个会卡住你的地方

---

## 5. T4 领域判定 + 粗筛（约 1.5 小时）→ **M1 完成**

### 交付

`filters/domain.py`、`filters/rank.py`

```python
def assign_domain(paper, domains_cfg) -> str
    # 规则1：分类只出现在一个领域的 categories 里 → 直接归它
    # 规则2：跨领域（cs.RO）且 aerospace 关键词命中标题 → aerospace
    # 规则3：embodied 关键词命中标题 → embodied
    # 规则4：按 domains 书写顺序，第一个包含 paper.primary_category 的
    #         （primary_category 为空时回退 categories[0]）

def score(paper, keywords) -> float   # 标题命中×3 + 摘要命中×1 + 录用词×5
def top_n(papers, keywords, n=30) -> list[Paper]   # 按 score 降序，必须保证有序
```

规则 1 必须在最前，否则 cs.CV 的无人机论文会被规则 2 抢走。  
`top_n` 必须保证输出有序 —— T6 的补位逻辑依赖这一点。

### 验收

```powershell
.venv\Scripts\python -c "
from sources.arxiv import fetch_all
from filters.domain import assign_domain
from config import load
from collections import Counter
c=load()
ps=fetch_all(['cs.AI','cs.LG','cs.CV','cs.CL','cs.RO','eess.SY','physics.flu-dyn'], c['run'])
cnt=Counter(assign_domain(p,c['domains']) for p in ps)
print(cnt)
assert set(cnt)=={'computer','embodied','aerospace'} and cnt['aerospace']>0, '领域判定异常'
assert cnt['aerospace'] < cnt['embodied'], 'cs.RO 冲突消解可能失效'
print('domain ok')
"
```

硬断言比"看着差不多"可靠。

### 卡点

- aerospace 为 0 → 关键词太窄，先看几条 cs.RO 标题里实际用什么词

---

## 6. T5 LLM 客户端（约 1 小时）

### 交付

`summarize/client.py`

````python
class JsonError(Exception): ...

def chat(cfg, messages, temperature=0.3, max_retries=2) -> str
    # POST {base_url}/chat/completions
    # trust_env=False；timeout=run.timeout_sec
    # 打印耗时 + usage.total_tokens（便于估成本）

def chat_json(cfg, messages, expect_keys: list[str]) -> dict
    # chat → 剥 ```json 围栏 → json.loads
    # expect_keys 里的 key 缺任一 → 视为失败
    # 失败重试 1 次（追加"只输出 JSON"）
    # 仍失败 → raise JsonError
````

`expect_keys` 的含义要在注释里写清楚：返回的 dict 必须含这些键，缺一个就当 JSON 失败走重试。否则 T6 会误用。

### 验收

```powershell
.venv\Scripts\python -c "
from config import load
from summarize.client import chat
c=load(); print(chat(c,[{'role':'user','content':'回一句话证明你活着'}]))
"
```

### 卡点

- 401 → 先看**百炼控制台的额度与模型开通状态**，再怀疑 key（额度耗尽和 key 错表现一样）
- 404 → base_url 少了 `/v1`

---

## 7. T6 精选（约 2 小时）—— **全项目最关键**

### 交付

`summarize/pick.py`、`prompts/pick.txt`

```python
def pick(domain_key, candidates, quota, cfg) -> list[Paper]
    # 前提：candidates 已按 score 降序（T4 的 top_n 保证）
    # 1) 拼清单 "序号. 标题 | 摘要前200字符"
    # 2) 填 prompts/pick.txt 的 {{domain}} {{candidates}} {{quota}}
    # 3) chat_json，取 picked
    # 4) 校验 id 在候选集（比对前先剥 vN）
    # 5) 不足 quota → 取 candidates 里前 N 个未被选中的补位
```

**`prompts/pick.txt` 必须包含**：

- 只输出 JSON，不要代码块
- schema：`{"picked":[{"id":"...","reason":"..."}]}`
- 排除标准：增量改进、纯刷榜、无新机制的
- `id` 必须从清单原样复制

文件末尾加 `__main__`：从 config 起，抓 → 判 → top_n → pick，每个领域打印 3 条。

### 验收

```powershell
.venv\Scripts\python -m summarize.pick
```

每个领域 3 条，带 reason，**且 id 都能在候选清单里找到**。

### 卡点

- 模型只给 2 条 → 补位逻辑必须生效，**当场写 `tests/test_pick_fallback.py`，不要留到 T12**
- 返回 id 带 `v1` → 比对前统一剥版本号

---

## 8. T7 总结（约 1.5 小时）

### 交付

`summarize/write.py`、`prompts/write.txt`

```python
def write_one(paper, cfg) -> Paper
    # 填 {{title}} {{abstract}} {{comment}}
    # chat_json 取 tldr / detail
    # tldr 超 100 字 → 截到最后一个句号（不是硬切）
    # detail 不足 250 字 → 记 warning，不判失败
    # 成功 llm_ok=True；异常 llm_ok=False 且 tldr/detail 留空

def write_all(papers, cfg) -> list[Paper]
    # 串行，每篇之间 sleep 1 秒
    # 打印 [3/9] 2610.31670 ok (4.2s)
```


文件末尾加 `__main__`。

### 验收

```powershell
.venv\Scripts\python -m summarize.write
```

**可证伪的验收**：9 篇里 `llm_ok=True` 的**不少于 7 篇**，且这些 tldr 长度在 60–100 字。
（原计划写"9 篇都有 tldr"自相矛盾 —— 允许失败就不可能全都有。）

### 卡点
- 模型爱写"本文提出..." → prompt 里给一个反例
- 中文按字符算：`len(tldr)` 对汉字是对的

---

## 9. T8 渲染（约 2 小时）

### 交付
`render/text.py`、`render/html.py`、`templates/qq.txt`、`templates/daily.html`

```python
# text.py
def render(papers_by_domain, date, public_url, cfg) -> str
    # 链接 = f"{public_url}daily-{date}.html#{paper.id}"
    # 填 templates/qq.txt 的 {{sections}} {{date}}

# html.py
def render(papers_by_domain, date, prev_date, public_url, template_path) -> str
    # 每篇 <article id="{paper.id}">
    # 填 templates/daily.html 的 {{cards}} {{date}} {{prev_link}}
```

**降级渲染（评审 I5，原计划漏了）**：

| 情形 | 输出 |
|---|---|
| 某领域抓取失败 | 该节一行「本领域今日抓取失败」 |
| `llm_ok=False` | 「总结生成失败，点链接看原文」 |
| `prev_date` 为空 | `{{prev_link}}` 渲染为「（无上一期）」 |

**`prev_date` 怎么来（评审 I4）**：扫描 `{repo_dir}/{site_dir}` 下所有 `daily-*.html`，取小于 `date` 的最大值；没有就传空串。不要用"昨天" —— 周末不生成 HTML，"昨天"这文件大概率不存在。

**占位符固定**：`{{date}}` `{{sections}}` `{{cards}}` `{{prev_link}}`。
渲染用 `str.replace`，**不要 `str.format`**（CSS 里的 `{}` 会炸）。

### 验收

```powershell
.venv\Scripts\python -m render.html --out outbox\preview-2026-10-24.html
Start-Process outbox\preview-2026-10-24.html
```

必须满足：
- 9 个卡片
- 手改一篇 `llm_ok=False` 再渲染，该卡片显示"总结生成失败"
- 点卡片标题能跳锚点

### 卡点
- 中文乱码 → 写文件 `encoding="utf-8"`
- 锚点跳不过去 → `<article>` 的 id 要等于裸 ID（不带 v1）

---

## 10. T9 发布到 Pages（约 1 小时）

### 交付
`publish/pages.py`

```python
def publish(repo_dir, site_dir, filename, content, branch, date) -> None
    # 1) path = os.path.join(repo_dir, site_dir, filename)；写文件 encoding="utf-8"
    # 2) git add -A
    # 3) git diff --cached --quiet → 无变更则跳过 commit（评审 I6）
    #    有变更才 git commit -m f"daily: {date}"
    # 4) git push origin {branch}
    # 5) 失败重试 2 次；仍失败 raise
```

**为什么第 3 步要判断**：同一天重跑时内容相同，`git commit` 报 "nothing to commit" 返回 1，`check=True` 直接抛异常，看起来像凭证坏了。

### 验收

```powershell
.venv\Scripts\python -c "
from config import load
c=load(); print(c['publish']['public_url']+'daily-2026-10-24.html')
"
# 手动跑一次发布后，浏览器打开上面打印的地址
```

### 卡点
- push 成功但 404 → 先等 60 秒；仍是 404 回 T1 查 Pages Source
- `public_url` 路径段 ≠ 仓库名 → 必 404

---

## 11. T10 QQ 推送（约 1 小时）

### 交付
`sinks/qq.py`

```python
def send_group(api_base, group_id, message, token="", timeout=20, retries=2) -> None
    # POST {api_base}/send_group_msg
    # body {"group_id": int(group_id), "message": message}
    # token 非空 → headers["Authorization"] = f"Bearer {token}"
    # 返回 retcode 非 0 → 抛异常；失败重试 2 次
```

**v1 不分条**（9 篇约 2000 字，远低于上限）。`max_message_chars` 只做断言：超了记 warning，不切分。

### 验收

```powershell
.venv\Scripts\python -c "
from config import load; from sinks.qq import send_group
c=load(); send_group(c['qq']['api_base'], c['qq']['group_id'], '测试一条，忽略',
                     token=c['qq'].get('access_token',''))
"
```

### 卡点
- 连不上 → NapCat 的 HTTP 服务端没开
- 返回 1404 → 群号不对或机器人不在群里
- 设了 token 却发不出 → 检查 `Authorization: Bearer` 头

---

## 12. T11 编排 + 定时（约 2 小时）→ **M3 完成**

### 交付
`main.py`

```python
def run(dry_run=False, ignore_history=False, resend_date=None):
    # 0  sys.stdout.reconfigure(encoding="utf-8")   ← 评审 I10，否则 --dry-run 打印 ▍ 就崩
    # 1  log_util.setup() / config.load()           失败 → exit(1)
    # 2  conn = store.init(cfg["store"]["db_path"])
    # 3  run_date = datetime.now().strftime("%Y-%m-%d")   ← 本地时区，全流程只用它
    # 3b if resend_date: 读 outbox/{resend_date}.txt → send_group → return   ← 评审 I7
    # 4  fetch_all()                                失败 → 记日志，继续
    # 5  assign_domain 分组
    # 6  filter_unpushed（ignore_history 时跳过）
    # 7  if 所有领域候选总数为 0: 记日志"今日无新论文"; return   ← 评审 B2
    # 8  每领域: top_n(30) → 空则降级 continue → pick(quota) → 失败该领域跳过
    # 9  write_all()                                单篇失败不影响其他
    # 10 render text/html
    # 11 if dry_run: 写 outbox/preview-{date}.html，打印文本，return
    # 12 publish.pages()                            重试 2 次仍失败 → 不发消息，写 outbox/{date}.txt，return
    # 13 sleep 60
    # 14 qq.send_group()                            重试 2 次仍失败 → 写 outbox/{date}.txt，return
    # 15 store.mark_pushed()                        ← 只有走到这里才记账
```

**三条硬要求**：

1. **`mark_pushed` 必须在发群成功之后**。反了，一次网络抖动就让这批论文永久丢失。
2. **空数据必须早退**（步骤 7）。没这个判断，周末或 key 未生效时会发布一张空 HTML，还覆盖掉好页面。
3. **`run_date` 全流程唯一**。文件名、QQ 文案、去重记录、链接都用它，不要混用论文的 `date`。

参数：`--dry-run`、`--ignore-history`、`--resend YYYY-MM-DD`。

### 验收

```powershell
# 1) 先看输出（会真调 LLM，约 2 分钟、一两毛钱，改 prompt 时天天用）
.venv\Scripts\python main.py --dry-run

# 2) 跳过去重再跑一次，确认流程完整
.venv\Scripts\python main.py --ignore-history --dry-run

# 3) 空数据分支：临时把 window_hours 改成 1，期望打印「今日无新论文」、退出码 0、outbox 无新文件
.venv\Scripts\python main.py --dry-run

# 4) 最后才真发
.venv\Scripts\python main.py
```

**顺序不能改**：第 4 步会 `mark_pushed` 9 篇，先跑它的话，当天再 `--dry-run` 就变成"无新论文"了。

### 计划任务（7:30）

```
程序：C:\Users\guff\Desktop\search the paper\.venv\Scripts\python.exe
参数：main.py
起始于：C:\Users\guff\Desktop\search the paper
```

任务属性里**必须勾选**：
- 「唤醒计算机运行此任务」
- 「如果错过计划开始时间，尽快启动任务」

不勾的话：7:30 笔记本合盖休眠 → 当天静默跳过，`logs/run.log` 一行都没有，你会以为是代码问题。

**验收**：把时间改到 2 分钟后 → 合盖 → 等 3 分钟 → 打开，看 `logs/run.log` 是否新增一行。

### 卡点
- 计划任务跑但没反应 → "起始于"没设，相对路径全失效
- `%USERPROFILE%` 不展开 → 用绝对路径

---

## 13. T12 测试补齐（约 2 小时，可与 T9–T11 穿插）

| 文件 | 断言 | 为什么必须 |
|---|---|---|
| `test_dedup.py` | 同 ID 的 v1/v2 只留一条 | 出错表现为"几天后重复推送"，肉眼极难发现 |
| `test_domain.py` | cs.RO 的 4 种情形各自归对 | 出错表现为"某栏目长期空缺" |
| `test_rank.py` | 关键词权重顺序正确 | 出错表现为"选出来都不相关" |
| `test_pick_fallback.py` | 模型少给时能补位 | **在 T6 当场写，不留到最后** |
| `test_render.py` | 文本 9 条、HTML 9 个卡片、`llm_ok=False` 显示降级文案 | 规格 §13 要求的集成测试 |

`tests/fixtures/sample_arxiv.xml` 存一份今天抓的真实响应（100 条）。

### 验收

```powershell
.venv\Scripts\python -m pytest tests -q
# 期望：5 passed
```

---

## 14. 依赖顺序

```
T0 ──► T2 ──► T3 ──► T4 ──► T5 ──► T6 ──► T7 ──► T8 ──► T9 ──► T10 ──► T11
 │                             │                              ▲
 ├─► T1（可全程并行）───────────┴──────────────────────────────┘
                                T12（穿插，test_pick_fallback 紧跟 T6）
```

- **T1 可全程并行**（只需要 GitHub 账号）
- **T5 可与 T4 并行**
- **T9/T10 可与 T8 并行**（都只需要最终字符串）
- 其余严格串行

---

## 15. 风险清单

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| **计划任务在休眠/未登录时不跑** | **高** | 当天完全静默 | 勾选"唤醒计算机"+"错过则尽快启动"；用合盖测试验收 |
| LLM 返回 JSON 不稳定 | 高 | 精选/总结失败 | 剥围栏 + 重试 + 上层标 `llm_ok=False` |
| arXiv 周末无新论文 | 高 | 验收时"没数据" | 72h 窗口；`--ignore-history`；周一再验 |
| **精选质量不达标** | 中 | 日报没价值 | 最大风险，见下 |
| Pages 构建延迟 | 中 | 点开 404 | push 后 sleep 60 |
| NapCat HTTP 未开 / token 未带 | 中 | 发不出 | T10 单独验收，先手工发一条 |
| 系统代理干扰 | 中 | 请求 502 | 所有 requests 用 `trust_env=False` |
| git commit 空变更报错 | 中 | 重跑时"发布失败" | commit 前判 `git diff --cached --quiet` |
| 百炼额度耗尽 | 低 | 全链路 401 | 卡点写明"先查额度再看 key" |

**最大风险是精选质量，不是技术。** 400 篇选 9 篇，选错这个产品就没价值。T6 的 prompt 要预留 2–3 轮迭代：先跑两周真实推荐，再调。

---

## 16. 里程碑

| 里程碑 | 任务 | 你能亲眼看到 |
|---|---|---|
| **M1 采集** | T0–T4 | 「去重后 342 篇：计算机 278 / 具身 52 / 飞行器 12」 |
| **M2 总结** | T5–T8 | 浏览器打开，9 个卡片，每篇 300–500 字 |
| **M3 闭环** | T9–T11 | 群里收到一条消息，手机点链接能打开 |

---

## 17. 需要你提供（阻塞项）

| 项 | 阻塞 | 说明 |
|---|---|---|
| `qq.group_id` | T10 | 群号 |
| `publish.repo_dir` / `public_url` | T1 | 仓库路径 + Pages 地址 |
| `DASHSCOPE_API_KEY` | T5 | 百炼 Key |
| **`templates/qq.txt`** | T8 | 你稍后提供 |
| **`templates/daily.html`** | T8 | 你稍后提供 |

前四项不影响 T0–T7；后两项在 T8 之前给即可。

---

## 18. 部署形态（v1.1 增量，不属于 v1 范围）

**v1 先在全本地跑通**（T0–T12）。跑通之后再决定要不要上服务器 —— 否则你同时调试"服务器环境"和"代码逻辑"两件事，出错时无法定位是哪边的问题。

### 18.1 为什么不能"整体搬到服务器"

抓取、总结、生成 HTML、推 Pages 都是纯 HTTP，放哪都行。**唯独"发到 QQ 群"搬不走**：NapCat 的本质是在一台机器上登录一个真实 QQ 账号，搬到云服务器会遇到异地登录验证、掉线保活、甚至账号冻结。

因此 v1.1 的形态是**拆分**：

```
云服务器（7:00 定时）
  ├─ 抓取 → 筛选 → 精选 → 总结 → 生成 HTML
  ├─ git push → GitHub Pages（网页永远最新，不依赖你开机）
  └─ 把 QQ 文案写进 site 仓库的 outbox/ 目录
                    │
                    ▼
本地（你开机后，计划任务每 10 分钟）
  └─ 拉取 outbox/ 里未发送的文件 → 调本机 NapCat → 发群 → 标记已发
```

**这个形态解决什么**：网页上的日报不会断档，哪怕你一个月不开机。
**这个形态不解决什么**：群消息仍然要等你开机才到。想彻底不等，只有把 NapCat 也搬上云 —— 那就承担 QQ 风控风险。

### 18.2 T13 服务器部署（约 3 小时）

| 步骤 | 内容 | 卡点 |
|---|---|---|
| 1 | 服务器装 Python 3.10+、git、配 SSH key | 国内镜像源装依赖更快 |
| 2 | `git clone` 两个仓库：代码库 + site 库 | 见下方"GitHub 连通性" |
| 3 | 装依赖、建 venv、填 config | 服务器上的 config 与本地分开维护 |
| 4 | `main.py` 加 `--no-push` 参数：只生成不推送，文案写入 `outbox/` | 这是唯一需要改的代码 |
| 5 | 配置 SSH over 443（见下） | — |
| 6 | crontab：`0 7 * * * cd /opt/paper-radar && .venv/bin/python main.py --no-push` | 时区要设成 Asia/Shanghai |
| 7 | 新增 `notify_local.py`：拉取 site 库 → 找 `outbox/*.txt` → 发群 → `git rm` 标记已发 | 本地计划任务每 10 分钟跑 |
| 8 | 验收：服务器手动跑一次 → 检查 Pages 更新 → 本地开机后 10 分钟内收到群消息 | — |

### 18.3 国内服务器最大的坑：连不上 GitHub

国内节点的云服务器访问 `github.com` 经常超时，`git push` 会直接失败。这不是配置问题，是网络问题。

**解法（第一次 push 前就要配好）**：

```
# ~/.ssh/config
Host github.com
  HostName ssh.github.com
  Port 443
  User git
```

即把 GitHub 的 SSH 走 443 端口，能绕过大部分封锁。配完用 `ssh -T git@github.com` 验证。

**备选**：用 GitHub REST API 提交文件（`PUT /repos/{owner}/{repo}/contents/{path}`）代替 `git push`，走 HTTPS。代码量大一些，但不依赖 git 的 SSH 通路。

### 18.4 服务器 vs GitHub Actions：如果你只是要"不用开机"

| | 云服务器 | GitHub Actions |
|---|---|---|
| 成本 | 约 100–300/年 | 公开仓库免费 |
| 运维 | 你要管系统更新、进程守护、磁盘、日志 | 零运维 |
| 定时精度 | cron 准点 | 有 5–15 分钟延迟，高峰期更久 |
| GitHub 连通性 | 国内节点可能连不上，要配 443 | 原生可达 |
| 适合 | 你已经有服务器，顺便复用 | 不想管机器 |

**如果服务器只是为了跑这个日报，Actions 更划算** —— 你已经有 GitHub 账号，公开仓库的 Actions 分钟数免费。但 Actions 的 cron 不准点，7:00 的任务可能 7:12 才跑。

### 18.5 需要你补充的信息

| 项 | 用途 |
|---|---|
| 服务器系统（Ubuntu / Debian / CentOS） | 决定装依赖的命令 |
| 服务器地区（国内 / 海外） | 决定是否需要 SSH over 443 |
| 配置（几核几 G） | 这个任务 1 核 1G 都够，主要确认不会有内存问题 |

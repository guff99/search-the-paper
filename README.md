# search-the-paper · 论文日报

每天早上自动抓取 arXiv 新论文，用 LLM 挑出值得看的几篇，写成六节解读，
发布成网页并推送到 QQ 群。

## 工作流

```
arXiv API 抓取（7 个分类）
      ↓
领域判定（关键词优先，其次看分类）
      ↓
关键词粗筛 Top-N  →  LLM 精选（每领域 3 篇）
      ↓
LLM 逐篇写「一句话总览 + 六节解读」
      ↓
渲染 QQ 纯文本 + HTML 卡片页
      ↓
发布到 GitHub Pages（git push，失败时走 REST API 兜底）
      ↓
NapCat（OneBot HTTP）推送到 QQ 群
      ↓
记账去重（SQLite）
```

## 目录

| 路径 | 作用 |
|---|---|
| `main.py` | 主流程入口，`--dry-run` 只生成不发送 |
| `config.py` / `config.yaml` | 配置加载与配置本体 |
| `sources/arxiv.py` | arXiv 抓取与解析 |
| `filters/` | 领域判定、关键词粗筛 |
| `summarize/` | LLM 客户端、精选、逐篇写作 |
| `render/` | QQ 文本与 HTML 渲染 |
| `publish/pages.py` | 发布到 GitHub Pages |
| `sinks/qq.py` | OneBot HTTP 推送 |
| `store.py` | 已推送去重库 |
| `prompts/` | 筛选与写作的 Prompt（可直接改） |
| `templates/` | 日报 HTML、QQ 文本、控制台页面 |
| `console.py` | 本地 / 云端控制台（标准库 `http.server`） |
| `docs/` | 设计、计划、评审与决策记录 |

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Linux: .venv/bin/pip

# LLM 的 Key 走环境变量，不写进配置文件
setx DASHSCOPE_API_KEY "sk-..."                    # Linux: export DASHSCOPE_API_KEY=...

python -m config                                   # 自检：配置能否加载
python main.py --dry-run                           # 彩排：只生成 HTML，不发布不推送
python main.py                                     # 正式：发布 + 推送 + 记账
```

## 配置要点（config.yaml）

| 键 | 说明 |
|---|---|
| `llm.base_url` / `llm.model` | 任何 OpenAI 兼容端点；默认 DeepSeek |
| `llm.api_key_env` | 从哪个环境变量读取 Key |
| `domains.*.categories` | 该领域抓取的 arXiv 分类 |
| `domains.*.keywords` | 粗筛打分用的关键词 |
| `domains.*.quota` | 每期篇数 |
| `domains.*.enabled` | 是否参与抓取与渲染 |
| `qq.api_base` | NapCat 的 OneBot HTTP 地址，默认 `127.0.0.1:3000` |
| `qq.group_id` | 推送目标群号 |
| `qq.access_token` | NapCat 的 token，留空表示不鉴权 |
| `publish.repo_dir` | 站点仓库的本地路径 |
| `publish.public_url` | 站点公开地址，结尾必须带 `/` |

## 控制台

```bash
python console.py            # 打开 http://127.0.0.1:8766/
```

单页界面：改两个 Prompt、增删领域、下拉选择论文来源、调篇数与关键词、
设置每日发送时间（Windows 用 `schtasks`，Linux 用 systemd timer）、
查看运行日志与历史日报。

## 部署

- **Windows**：计划任务调用 `python main.py`，勾选「唤醒计算机」「错过则尽快启动」
- **Linux**：`systemd` 的 `.service` + `.timer`，用 `EnvironmentFile` 提供 Key
- **QQ 推送**：需要 NapCat（Docker 或桌面端），在其中登录一个 QQ 小号

## 测试

```bash
python -m pytest tests -q
```

## License

MIT

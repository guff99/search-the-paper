"""单文件 HTML 渲染：内联样式，不依赖任何 CDN。

两个关键点：
- 每个卡片是 <article id="{裸ID}">，这样 QQ 消息里的 #2610.31670 能直接跳过去
- 用 str.replace 渲染模板，**不用 str.format** —— CSS 里的 {} 会把它炸掉
"""

import glob
import html
import os

from config import enabled_domains

TEMPLATE_PATH = os.path.join("templates", "daily.html")

PAPER_FAIL = "总结生成失败，点链接看原文"
DOMAIN_FAIL = "本领域今日抓取失败"
NO_PREV = "（无上一期）"


def find_prev_date(pages_dir: str, date: str) -> str:
    """扫描站点目录里已发布的 daily-*.html，取小于 date 的最大日期。

    不用"昨天" —— 周末不生成 HTML，"昨天"这个文件大概率不存在。
    """
    if not pages_dir or not os.path.isdir(pages_dir):
        return ""
    found = []
    for path in glob.glob(os.path.join(pages_dir, "daily-*.html")):
        name = os.path.basename(path)
        d = name[len("daily-") : -len(".html")]
        if d < date:
            found.append(d)
    return max(found) if found else ""


_SEC_MARKS = ("一、", "二、", "三、", "四、", "五、", "六、",
              "七、", "八、", "九、", "十、")


def _detail_html(detail: str) -> str:
    """把「六节纯文本解读」拆成 <h3> 小标题 + <p> 正文，让模板能上样式。

    模型偶尔会把标题和正文挤在同一行，或某节没有编号 —— 这种段落按普通
    文字渲染即可，降级可读，不抛异常。
    """
    parts = []
    for para in (detail or "").strip().split("\n\n"):
        para = para.strip()
        if not para:
            continue
        lines = para.split("\n")
        head = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        if head.startswith(_SEC_MARKS):
            parts.append(f'<h3 class="sec">{html.escape(head)}</h3>')
            if body:
                parts.append(f'<p class="sec-body">{html.escape(body)}</p>')
        else:
            parts.append(f'<p class="detail-para">{html.escape(para)}</p>')
    return "\n  ".join(parts)


def _card(p) -> str:
    e = html.escape
    meta_parts = []
    if p.authors:
        meta_parts.append(e(p.authors_str(3)))
    if p.comment:
        meta_parts.append(e(p.comment))
    meta = " · ".join(meta_parts)

    tldr_block = (
        f'<div class="overview"><span class="overview-label">一句话总览</span>{e(p.tldr)}</div>'
        if p.llm_ok
        else f'<div class="tldr fail">{PAPER_FAIL}</div>'
    )
    detail_block = (
        f'<div class="detail">{_detail_html(p.detail)}</div>' if p.llm_ok else ""
    )

    return (
        f'<article id="{e(p.id)}">\n'
        f'  <div class="t">{e(p.title)}</div>\n'
        f'  <div class="meta">{meta}</div>\n'
        f"  {tldr_block}\n"
        f"  {detail_block}\n"
        f'  <div class="links"><a href="{e(p.abs_url)}" target="_blank">arXiv 原文</a>'
        f' · <a href="{e(p.pdf_url)}" target="_blank">PDF</a></div>\n'
        f"</article>"
    )


def render(papers_by_domain: dict, date: str, prev_date: str, public_url: str,
           template_path: str = TEMPLATE_PATH, cfg=None) -> str:
    """渲染整页。cfg 只用来取领域名与顺序，不传也能跑（占位版）。"""
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()

    names = {}
    order = list(papers_by_domain.keys())
    if cfg and cfg.get("domains"):
        names = {k: v.get("name", k) for k, v in cfg["domains"].items()}
        order = list(enabled_domains(cfg).keys())

    blocks = []
    for key in order:
        papers = papers_by_domain.get(key) or []
        name = names.get(key, key)
        blocks.append(f"<h2>{html.escape(name)}</h2>")
        if not papers:
            blocks.append(f'<article><div class="fail">{DOMAIN_FAIL}</div></article>')
            continue
        blocks.extend(_card(p) for p in papers)

    prev_link = (
        f'<a href="{public_url}daily-{prev_date}.html">{prev_date}</a>'
        if prev_date
        else NO_PREV
    )

    return (
        tpl.replace("{{date}}", html.escape(date))
        .replace("{{cards}}", "\n  ".join(blocks))
        .replace("{{prev_link}}", prev_link)
    )


def write_file(content: str, path: str) -> None:
    """写文件（显式 utf-8 —— Windows 默认是 GBK，中文会乱码）。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    import argparse
    import sys
    from datetime import datetime

    sys.path.insert(0, ".")
    from config import load

    from models import Paper

    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="")
    ap.add_argument("--demo", action="store_true", help="用假数据渲染（不联网、不调 LLM）")
    args = ap.parse_args()

    cfg = load()
    date = datetime.now().strftime("%Y-%m-%d")

    if args.demo:
        def mk(pid, title, tldr, ok=True):
            p = Paper(
                id=pid, title=title, abstract="",
                authors=["Alice", "Bob", "Carol"],
                comment="Accepted at CoRL 2026",
                abs_url=f"http://arxiv.org/abs/{pid}v1",
                pdf_url=f"https://arxiv.org/pdf/{pid}v1",
                tldr=tldr, detail=("这是详细解读的第一段。\n" * 8),
            )
            p.llm_ok = ok
            return p

        data = {
            "computer": [mk(f"2610.0000{i}", f"示例论文 {i}", "一句话总结示例，这里应该有具体的数字和结论。") for i in range(1, 4)],
            "embodied": [mk(f"2610.1000{i}", f"具身示例 {i}", "真机上成功率从 41% 提到 78%。", ok=(i != 2)) for i in range(1, 4)],
            "aerospace": [mk(f"2610.2000{i}", f"飞行器示例 {i}", "四旋翼在 8m/s 侧风下轨迹误差从 0.42m 降到 0.11m。") for i in range(1, 4)],
        }
    else:
        from collections import defaultdict

        from filters.domain import assign_domain
        from filters.rank import top_n
        from sources.arxiv import fetch_all
        from summarize.pick import pick
        from summarize.write import write_all

        cats = []
        for d in cfg["domains"].values():
            for c in d["categories"]:
                if c not in cats:
                    cats.append(c)

        papers = fetch_all(cats, cfg["run"])
        grouped = defaultdict(list)
        for p in papers:
            dom = assign_domain(p, cfg["domains"])
            if dom:
                grouped[dom].append(p)

        data = {}
        selected = []
        for key in cfg["domains"]:
            cands = top_n(grouped.get(key, []), cfg["domains"][key]["keywords"], 30)
            got = pick(key, cands, cfg["domains"][key]["quota"], cfg)
            data[key] = got
            selected.extend(got)
        write_all(selected, cfg)

    prev = find_prev_date(
        os.path.join(cfg["publish"]["repo_dir"], cfg["publish"]["site_dir"]), date
    )
    page = render(data, date, prev, cfg["publish"]["public_url"], TEMPLATE_PATH, cfg)

    out = args.out or os.path.join("outbox", f"preview-{date}.html")
    write_file(page, out)
    n = sum(len(v) for v in data.values())
    print(f"已渲染 {n} 篇 → {out}（上一期：{prev or '无'}）")

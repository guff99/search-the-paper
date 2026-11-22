"""arXiv 采集：发 HTTP 请求拿 atom XML，解析成 list[Paper]。

四个坑（新手最容易卡在这）：
1. atom 标签带命名空间 → 一律用 findall("{*}xxx") 通配
2. <id> 是 http://arxiv.org/abs/2610.31670v1 → id 要剥 vN，abs_url 保留原样
3. <title>/<summary> 里有一堆换行 → 压成单空格
4. <arxiv:comment> 可能不存在 → 缺失给空串

代理：requests 一律 trust_env=False（实测走系统代理会 502，直连 200）。
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from models import Paper

API = "https://export.arxiv.org/api/query"

# 重试间隔：2 / 4 / 8 秒
BACKOFF = [2, 4, 8]

_WS = re.compile(r"\s+")
_VN = re.compile(r"v\d+$")

# trust_env 是 Session 的属性，requests.get() 不接受这个关键字参数。
#
# 【与规格 §5.1 的偏差，已由作者确认】规格原话是「直连，不走系统代理」，
# 但 2026-10-24 实测：直连 export.arxiv.org 连接超时（21 秒无响应），
# 走 Windows 系统代理（127.0.0.1:7897）返回 200 且能拿到真实数据。
# 所以这里设为 True —— 让 requests 读系统/环境变量里的代理。
# 若哪天直连恢复了，把这一行改成 False 即可，其余代码不用动。
SESSION = requests.Session()
SESSION.trust_env = True


def _clean(text: str) -> str:
    """去掉换行，压缩连续空白。"""
    if not text:
        return ""
    return _WS.sub(" ", text).strip()


def _strip_version(arxiv_id: str) -> str:
    """2610.31670v1 → 2610.31670（去重主键必须是裸 ID）。"""
    return _VN.sub("", arxiv_id)


def _find_text(node, path: str) -> str:
    """按通配命名空间取子节点文本，取不到返回空串。"""
    el = node.find(path)
    return el.text if el is not None and el.text else ""


def _parse_published(raw: str):
    """ISO 8601 → datetime(UTC)。解析不了返回 None。"""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _parse(xml_text: str) -> list[Paper]:
    """atom XML → list[Paper]。"""
    root = ET.fromstring(xml_text)
    papers = []

    for entry in root.findall("{*}entry"):
        raw_id = _find_text(entry, "{*}id")
        # http://arxiv.org/abs/2610.31670v1 → 2610.31670v1
        tail = raw_id.rsplit("/abs/", 1)[-1]

        published = _parse_published(_find_text(entry, "{*}published"))

        # 主分类：必须用 <arxiv:primary_category>，categories[0] 顺序不保证
        prim_el = entry.find("{*}primary_category")
        primary_category = prim_el.get("term", "") if prim_el is not None else ""

        categories = [
            c.get("term", "")
            for c in entry.findall("{*}category")
            if c.get("term")
        ]

        # PDF 链接：type="application/pdf" 的那个
        pdf_url = ""
        for link in entry.findall("{*}link"):
            if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                pdf_url = link.get("href", "")
                break

        papers.append(
            Paper(
                id=_strip_version(tail),
                title=_clean(_find_text(entry, "{*}title")),
                abstract=_clean(_find_text(entry, "{*}summary")),
                authors=[
                    _clean(a.text)
                    for a in entry.findall("{*}author/{*}name")
                    if a.text
                ],
                categories=categories,
                primary_category=primary_category,
                published=published,
                date=(published.date().isoformat() if published else ""),
                comment=_clean(_find_text(entry, "{*}comment")),
                abs_url=raw_id,
                pdf_url=pdf_url,
            )
        )

    return papers


def _get(url: str, run_cfg: dict) -> str:
    """带重试的 GET。全部失败就抛最后一次的异常（由 fetch_all 决定跳过还是报错）。"""
    retries = int(run_cfg.get("retries", 3))
    timeout = float(run_cfg.get("timeout_sec", 40))

    last = None
    for i in range(retries):
        try:
            resp = SESSION.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.text
        except Exception as e:  # 网络/HTTP 错误都重试
            last = e
            if i < retries - 1:
                wait = BACKOFF[min(i, len(BACKOFF) - 1)]
                print(f"    请求失败（{e}），{wait}s 后重试 {i + 2}/{retries}")
                time.sleep(wait)

    raise last


def fetch_category(category: str, run_cfg: dict) -> list[Paper]:
    """抓一个分类。日期过滤不在这里做（arXiv 的日期区间语法会查空）。"""
    limit = int(run_cfg.get("per_category_limit", 100))
    url = (
        f"{API}?search_query=cat:{category}"
        f"&start=0&max_results={limit}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    return _parse(_get(url, run_cfg))


def filter_window(papers, hours) -> list[Paper]:
    """只保留 published 在最近 hours 小时内的。

    arXiv 索引有约 1 天延迟，写死"抓昨天"会周期性漏数据，
    所以抓 3 天窗口 + 本地过滤，多出来的靠 SQLite 去重挡掉。
    """
    if not papers:
        return []
    now = datetime.now(timezone.utc)
    deadline = now - timedelta(hours=float(hours))
    kept = [p for p in papers if p.published and p.published >= deadline]
    return kept


def fetch_all(categories, run_cfg) -> list[Paper]:
    """逐分类抓 → 窗口过滤 → 合并 → 按 id 去重。

    单个分类失败只跳过该分类；全部失败才抛异常。
    """
    interval = float(run_cfg.get("request_interval", 3.0))
    hours = run_cfg.get("window_hours", 72)

    seen: dict[str, Paper] = {}
    ok_count = 0

    for cat in categories:
        try:
            raw = fetch_category(cat, run_cfg)
            kept = filter_window(raw, hours)
            ok_count += 1
            print(f"  {cat}: 抓取 {len(raw)} 条 → 窗口内 {len(kept)} 条")
            for p in kept:
                seen.setdefault(p.id, p)
        except Exception as e:
            print(f"  {cat}: 抓取失败（{e}），跳过该分类")
        time.sleep(interval)

    if ok_count == 0:
        raise RuntimeError("所有 arXiv 分类都抓取失败")

    result = list(seen.values())
    result.sort(key=lambda p: p.published or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True)
    return result


if __name__ == "__main__":
    # python -m sources.arxiv
    import sys

    sys.path.insert(0, ".")
    from config import load

    cfg = load()
    cats = []
    for d in cfg["domains"].values():
        for c in d["categories"]:
            if c not in cats:
                cats.append(c)

    print("分类：", cats)
    papers = fetch_all(cats, cfg["run"])

    print(f"\n去重后共 {len(papers)} 篇")
    if papers:
        oldest = min(p.published for p in papers if p.published)
        hours_ago = (datetime.now(timezone.utc) - oldest).total_seconds() / 3600
        print(f"最旧发布时间：{oldest.isoformat()}（距今 {hours_ago:.1f} 小时）")
        print(f"最新发布时间：{max(p.published for p in papers).isoformat()}")
        p = papers[0]
        print("\n样例：")
        print("  id:", p.id)
        print("  主分类:", p.primary_category, "| 全部分类:", p.categories)
        print("  标题:", p.short_title(60))
        print("  作者:", p.authors_str(3))
        print("  abs:", p.abs_url)
        print("  pdf:", p.pdf_url)
        print("  comment:", p.comment[:80])

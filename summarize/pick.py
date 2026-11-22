"""精选：让模型从 30 篇粗筛结果里挑出 quota 篇。

这是全项目最关键的一步 —— 抓 400 篇不难，选出对的那 3 篇很难。
一个领域一天只推 3 篇，选错了这个方向今天就等于没看。

前提：candidates 必须已按 score 降序（T4 的 top_n 保证），
因为模型少给的时候，补位是按这个顺序从前往后取的。
"""

import os
import re

from models import Paper
from summarize.client import JsonError, chat_json

_VN = re.compile(r"v\d+$")

PROMPT_PATH = os.path.join("prompts", "pick.txt")

# 清单里每篇摘要只取前这么多字符，控制输入 token
ABSTRACT_CHARS = 200


def _strip_version(arxiv_id: str) -> str:
    """模型偶尔会带回 v1 后缀，比对前统一剥掉。"""
    return _VN.sub("", str(arxiv_id or "").strip())


def _build_list(candidates) -> str:
    """序号. [id] 标题 | 摘要前 200 字符"""
    lines = []
    for i, p in enumerate(candidates, 1):
        abs_snip = (p.abstract or "")[:ABSTRACT_CHARS]
        lines.append(f"{i}. [{p.id}] {p.title} | {abs_snip}")
    return "\n".join(lines)


def _load_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def pick(domain_key: str, candidates, quota: int, cfg) -> list[Paper]:
    """从 candidates 里挑 quota 篇，返回带 picked_reason 的 list[Paper]。"""
    if not candidates:
        return []

    domain_name = (cfg["domains"].get(domain_key) or {}).get("name", domain_key)

    prompt = (
        _load_prompt()
        .replace("{{domain}}", domain_name)
        .replace("{{candidates}}", _build_list(candidates))
        .replace("{{quota}}", str(quota))
    )

    messages = [{"role": "user", "content": prompt}]

    # id → paper，只认候选集里的；模型给的 id 可能是 "2610.31670v1"
    index = {p.id: p for p in candidates}

    picked: list = []
    try:
        data = chat_json(cfg, messages, expect_keys=["picked"])
        raw_list = data.get("picked") or []
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            pid = _strip_version(item.get("id", ""))
            paper = index.get(pid)
            if paper is None:
                # 不在候选集里 —— 丢弃，不猜
                print(f"    [pick] 丢弃无效 id: {item.get('id')}")
                continue
            if paper in picked:
                continue
            paper.picked_reason = str(item.get("reason", "")).strip()
            picked.append(paper)
            if len(picked) >= quota:
                break
    except JsonError as e:
        print(f"    [pick] {domain_key} 精选调用失败：{e}")

    # 补位：模型给少了（或整个失败了），按粗筛分数顺位补齐
    if len(picked) < quota:
        need = quota - len(picked)
        already = {p.id for p in picked}
        for p in candidates:
            if p.id in already:
                continue
            picked.append(p)
            already.add(p.id)
            need -= 1
            if need <= 0:
                break
        print(f"    [pick] {domain_key} 模型只给了 {quota - need} 条，补位 {need if need > 0 else ''}")

    return picked[:quota]


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from collections import defaultdict

    from config import load
    from filters.domain import assign_domain
    from filters.rank import top_n
    from sources.arxiv import fetch_all

    cfg = load()

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

    for key in cfg["domains"]:
        cands = top_n(grouped.get(key, []), cfg["domains"][key]["keywords"], 30)
        quota = cfg["domains"][key]["quota"]
        print(f"\n=== {key}（候选 {len(cands)} → 选 {quota}）===")
        for p in pick(key, cands, quota, cfg):
            print(f"  {p.id}  {p.short_title(50)}")
            print(f"      理由：{p.picked_reason}")

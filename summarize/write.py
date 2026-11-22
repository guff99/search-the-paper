"""逐篇写总结：tldr（≤100 字）+ detail（1200–1600 字）。

串行执行，每篇之间 sleep 1 秒 —— 15 次调用约 2 分钟，在预算内。
并发对新手是灾难（线程里的异常难定位），v1 不并发。

单篇失败重试 1 次，仍失败就标 llm_ok=False，**继续下一篇** ——
一篇失败不能拖垮整份日报。
"""

import os
import re
import time

from sources import fulltext as fulltext_mod
from summarize.client import JsonError, chat_json

PROMPT_PATH = os.path.join("prompts", "write.txt")

TLDR_MAX = 100
DETAIL_MIN = 1000    # 低于这个数说明模型偷懒了，打条警告
DETAIL_MAX = 1600     # 程序级上限：超了按句子裁，不靠模型自觉

_SEC_RE = re.compile(r"^\s*[一二三四五六]、\S")


def _cut_tldr(text: str) -> str:
    """超过 100 字就截到最后一个句号（硬切会留下半句话）。"""
    t = (text or "").strip()
    if len(t) <= TLDR_MAX:
        return t
    head = t[:TLDR_MAX]
    pos = max(head.rfind("。"), head.rfind("."), head.rfind("！"), head.rfind("？"))
    return head[: pos + 1] if pos != -1 else head + "…"


def _split_sents(body: str) -> list[str]:
    """按中文句末标点切句，标点跟着前一句走。"""
    out, buf = [], ""
    for ch in body:
        buf += ch
        if ch in "。！？；":
            out.append(buf)
            buf = ""
    if buf.strip():
        out.append(buf)
    return [s for s in out if s.strip()]


def _trim_body(body: str, target: int) -> tuple[str, int]:
    """把一段正文裁到 target 字以内，返回（新正文, 删掉的句数）。

    优先删「不含数字」的句子 —— 实验数值是最难替代的信息，宁可留长句。
    """
    sents = _split_sents(body)
    if sum(len(s) for s in sents) <= target:
        return body, 0

    keep = list(sents)
    dropped = 0
    while len("".join(keep)) > target and len(keep) > 1:
        idx = None
        for i in range(len(keep) - 1, -1, -1):
            if not re.search(r"\d", keep[i]):
                idx = i
                break
        if idx is None:            # 全是带数字的句子，只能从末尾删
            idx = len(keep) - 1
        keep.pop(idx)
        dropped += 1
    return "".join(keep).strip(), dropped


def fit_detail(detail: str, limit: int = DETAIL_MAX) -> tuple[str, int]:
    """把超长 detail 裁到 limit 以内，保住「一、～六、」六节结构。

    为什么要在程序里兜底：实测模型对「1200–1600 字」这类字数指令不敏感，
    喂全文后稳定写到 2200–2500 字。按句子删至少不会出现半句话，
    比硬截断体面；六节标题一律保留，读者看到的仍是完整结构。
    """
    text = (detail or "").strip()
    if len(text) <= limit:
        return text, 0

    blocks: list[list[str]] = []
    cur: list[str] = []
    for ln in text.split("\n"):
        if _SEC_RE.match(ln) and cur:
            blocks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        blocks.append(cur)

    headed = [b for b in blocks if b and _SEC_RE.match(b[0])]
    if len(headed) < 6:            # 结构不符合预期就不动，交给人工看
        print(f"      warning: detail {len(text)} 字，但没认出六节结构，未裁剪")
        return text, 0

    overhead = sum(len(b[0]) + 1 for b in blocks) + 2 * (len(blocks) - 1)
    budget = max(limit - overhead, 600)
    total = sum(len("\n".join(b[1:])) for b in blocks) or 1

    dropped_all = 0
    out_blocks = []
    for b in blocks:
        head, body = b[0], "\n".join(b[1:]).strip()
        share = max(int(budget * len(body) / total), 120)
        new_body, dropped = _trim_body(body, share)
        # 删掉末句后可能留下「；」或「，」收尾，读起来像被切断，统一收成句号
        new_body = re.sub(r"[；，、,;]\s*$", "。", new_body)
        dropped_all += dropped
        out_blocks.append(head + ("\n" + new_body if new_body else ""))

    return "\n\n".join(out_blocks).strip(), dropped_all


def _load_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read()


def _fulltext_block(paper, scfg: dict) -> str:
    """给 prompt 用的全文段落。抓不到就给一句明确的降级说明。

    为什么要显式告诉模型「没取到全文」：否则它会照抄摘要却以为自己在写全文解读，
    读者也看不出这篇是降级产物。
    """
    if not (scfg or {}).get("fulltext", True):
        return "（本次运行关闭了全文抓取，只能依据下面的摘要）"

    text = fulltext_mod.fetch(paper, scfg)
    if text:
        return f"（以下是从 arXiv 抓到的论文全文，可能已截断）\n\n{text}"
    return "（没有取到全文，只能依据下面的摘要；请在「六、局限性」里注明这一点）"


def write_one(paper, cfg):
    """给一篇论文写总结，返回这篇 Paper（就地修改）。"""
    scfg = cfg.get("summarize") or {}
    prompt = (
        _load_prompt()
        .replace("{{title}}", paper.title or "")
        .replace("{{abstract}}", paper.abstract or "")
        .replace("{{comment}}", paper.comment or "（无）")
        .replace("{{fulltext}}", _fulltext_block(paper, scfg))
    )

    try:
        data = chat_json(
            cfg,
            [{"role": "user", "content": prompt}],
            expect_keys=["tldr", "detail"],
            timeout=float(scfg.get("timeout_sec", 150)),
        )
        paper.tldr = _cut_tldr(str(data.get("tldr", "")))
        raw_detail = str(data.get("detail", "")).strip()
        paper.detail, dropped = fit_detail(raw_detail)
        if dropped:
            print(f"      detail {len(raw_detail)} 字 → 裁到 {len(paper.detail)} 字（按句删 {dropped} 句，六节保留）")
        paper.llm_ok = True

        if len(paper.detail) < DETAIL_MIN:
            print(f"      warning: detail 只有 {len(paper.detail)} 字（不足 {DETAIL_MIN}），但不算失败")
    except JsonError as e:
        # 失败就留空，让渲染层显示降级文案
        print(f"      总结失败：{e}")
        paper.tldr = ""
        paper.detail = ""
        paper.llm_ok = False

    return paper


def write_all(papers, cfg):
    """串行写一批，返回同一批 Paper。"""
    total = len(papers)
    for i, p in enumerate(papers, 1):
        t0 = time.time()
        write_one(p, cfg)
        flag = "ok" if p.llm_ok else "FAIL"
        print(f"  [{i}/{total}] {p.id} {flag} ({time.time() - t0:.1f}s)")
        time.sleep(1)
    return papers


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from collections import defaultdict

    from config import load
    from filters.domain import assign_domain
    from filters.rank import top_n
    from sources.arxiv import fetch_all
    from summarize.pick import pick

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

    selected = []
    for key in cfg["domains"]:
        cands = top_n(grouped.get(key, []), cfg["domains"][key]["keywords"], 30)
        selected.extend(pick(key, cands, cfg["domains"][key]["quota"], cfg))

    print(f"\n共选出 {len(selected)} 篇，开始写总结")
    write_all(selected, cfg)

    ok = sum(1 for p in selected if p.llm_ok)
    print(f"\nllm_ok=True: {ok}/{len(selected)}")
    for p in selected:
        mark = "OK  " if p.llm_ok else "FAIL"
        print(f"  [{mark}] tldr {len(p.tldr):>3} 字 | detail {len(p.detail):>4} 字 | {p.short_title(40)}")

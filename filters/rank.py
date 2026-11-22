"""关键词粗筛（免费、零成本）。

    score = 标题命中关键词数 × 3
          + 摘要命中关键词数 × 1
          + comment 含录用词 × 5

只求"不漏掉明显相关的"，不追求精度 —— 真正的筛选交给 T6 的 LLM。
匹配大小写不敏感，同一关键词出现多次只算一次（数的是"命中了几个不同的关键词"）。
"""

from models import Paper

# comment 里出现这些词，说明论文被会议/期刊录用了，值得加权
ACCEPT_WORDS = ["accepted", "published", "to appear", "appearing"]

TITLE_WEIGHT = 3
ABSTRACT_WEIGHT = 1
ACCEPT_WEIGHT = 5


def _count_hits(text: str, keywords) -> int:
    """数命中的**不同**关键词个数（大小写不敏感）。"""
    low = (text or "").lower()
    return sum(1 for kw in keywords if kw.lower() in low)


def score(paper: Paper, keywords) -> float:
    """给一篇论文打分。"""
    s = _count_hits(paper.title, keywords) * TITLE_WEIGHT
    s += _count_hits(paper.abstract, keywords) * ABSTRACT_WEIGHT

    low_comment = (paper.comment or "").lower()
    if any(w in low_comment for w in ACCEPT_WORDS):
        s += ACCEPT_WEIGHT

    return float(s)


def top_n(papers, keywords, n: int = 30) -> list[Paper]:
    """按 score 降序取前 n 篇。**输出必须有序** —— T6 的补位逻辑依赖这个顺序。"""
    scored = list(papers)
    for p in scored:
        p.score = score(p, keywords)

    # sorted 是稳定排序：分数相同时保持原顺序（输入是按发布时间倒序的）
    scored.sort(key=lambda p: p.score, reverse=True)
    return scored[:n]


if __name__ == "__main__":
    # 5 篇假 Paper，验证权重顺序：录用 > 标题 > 摘要
    def mk(title, abstract, comment=""):
        return Paper(id=title[:8], title=title, abstract=abstract, comment=comment)

    papers = [
        mk("A LLM benchmark", "nothing here"),                       # 标题1 = 3
        mk("Diffusion for images", "we use diffusion and LLM"),      # 标题1+摘要2 = 5
        mk("Nothing", "nothing", "Accepted at NeurIPS 2026"),        # 录用 = 5
        mk("Transformer LLM agent", "transformer"),                  # 标题3 = 9
        mk("Random title", "random abstract"),                       # 0
    ]

    out = top_n(papers, ["transformer", "diffusion", "LLM", "benchmark", "agent"], n=5)
    for p in out:
        print(f"  {p.score:>5.1f}  {p.title}")

    assert out[0].title == "Transformer LLM agent", "标题权重未生效"
    assert out[-1].score == 0, "零分论文应排最后"
    print("rank ok")

"""关键词打分：标题权重 > 摘要权重，录用信息再加权。

出错表现是"选出来的都不相关"。
"""

from filters.rank import score, top_n
from models import Paper

KEYWORDS = ["transformer", "diffusion", "LLM", "benchmark", "agent"]


def _mk(title, abstract, comment=""):
    return Paper(id=title[:10], title=title, abstract=abstract, comment=comment)


def test_title_weighs_more_than_abstract():
    a = _mk("A LLM benchmark", "nothing")          # 标题命中 2 → 6
    b = _mk("Nothing", "we use LLM and benchmark")  # 摘要命中 2 → 2
    assert score(a, KEYWORDS) > score(b, KEYWORDS)


def test_accept_bonus():
    a = _mk("Nothing", "nothing", "Accepted at NeurIPS 2026")
    b = _mk("A LLM benchmark", "nothing")
    assert score(a, KEYWORDS) == 5
    assert score(b, KEYWORDS) == 6          # 标题两命中 = 6 > 录用 5
    assert score(a, KEYWORDS) < score(b, KEYWORDS)


def test_case_insensitive_and_distinct_only():
    a = _mk("LLM llm LlM", "")          # 同一关键词出现三次，只算一次
    assert score(a, KEYWORDS) == 3


def test_top_n_is_ordered():
    papers = [
        _mk("Random", "random"),                    # 0
        _mk("Transformer LLM agent", "x"),          # 9
        _mk("A LLM benchmark", "x"),                # 6
        _mk("Diffusion", "diffusion and LLM"),      # 3 + 2 = 5
        _mk("Nothing", "nothing", "Accepted at X"), # 5
    ]
    out = top_n(papers, KEYWORDS, 3)
    assert [p.score for p in out] == sorted((p.score for p in out), reverse=True)
    assert out[0].title == "Transformer LLM agent"
    assert len(out) == 3

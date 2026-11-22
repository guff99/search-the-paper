"""全文抓取模块的单测：只测纯函数与截断策略，不碰网络。"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Paper          # noqa: E402
from sources import fulltext      # noqa: E402


SAMPLE = """
<html><body>
<div class="ltx_page_header">Content selection saved. Describe the issue below</div>
<div class="ltx_page_content">
<h1>Test Paper</h1>
<p>arXiv:2611.00001v1 [cs.CV] 19 Nov 2026</p>
<h2>1 Introduction</h2>
<p>We study   the problem.</p>
<math alttext="x^2"></math>
<h2>2 Method</h2>
<p>Our method has two parts.</p>
<h2>References</h2>
<p>[1] Someone. A paper.</p>
</div>
</body></html>
"""


def test_extract_keeps_text_and_drops_header():
    text = fulltext.extract(SAMPLE)
    assert "We study the problem." in text
    assert "Our method has two parts." in text
    # 页头 class 在 SKIP_CLASSES 里，应被整块丢掉
    assert "Content selection saved" not in text


def test_extract_keeps_math_alttext():
    text = fulltext.extract(SAMPLE)
    assert "x^2" in text


def test_strip_front_matter_drops_page_shell():
    text = fulltext.extract(SAMPLE)
    stripped = fulltext._strip_front_matter(text)
    assert "Test Paper" not in stripped          # 水印行之前的内容都不要
    assert stripped.startswith("1 Introduction") or "Introduction" in stripped


def test_trim_references():
    # 少于 2000 字不裁（避免误伤短文档），所以这里造一段长文本
    text = ("正文内容。" * 500) + "\n\nReferences\n\n[1] Someone. A paper.\n"
    trimmed = fulltext._trim_references(text)
    assert "Someone. A paper." not in trimmed
    assert trimmed.startswith("正文内容。")


class _FakePaper:
    def __init__(self, pid):
        self.id = pid


def test_truncation_keeps_head_and_tail(monkeypatch):
    """超过上限时必须保头保尾 —— 实验和结论都在尾部。"""
    body = "HEAD " + ("A" * 2000) + "\n\n" + ("B" * 2000) + " TAIL experiments 0.805"
    monkeypatch.setattr(fulltext, "_get", lambda *a, **k: f"<html><body><p>{body}</p></body></html>")
    monkeypatch.setattr(fulltext, "MIN_CHARS", 10)

    out = fulltext.fetch(_FakePaper("1234.5678"),
                         {"fulltext": True, "fulltext_max_chars": 400, "fulltext_timeout": 5})
    assert "中间部分因篇幅省略" in out
    assert out.startswith("HEAD")
    assert "0.805" in out


def test_fetch_returns_empty_when_disabled(monkeypatch):
    monkeypatch.setattr(fulltext, "_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该被调用")))
    assert fulltext.fetch(_FakePaper("1234.5678"), {"fulltext": False}) == ""


def test_fetch_returns_empty_when_too_short(monkeypatch):
    monkeypatch.setattr(fulltext, "_get", lambda *a, **k: "<html><body><p>短</p></body></html>")
    assert fulltext.fetch(_FakePaper("1234.5678"), {"fulltext": True}) == ""

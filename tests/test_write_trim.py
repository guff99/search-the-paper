"""detail 长度兜底的测试：模型不听话时，程序要能把话说完整地压回去。"""

from summarize.write import DETAIL_MAX, fit_detail

HEADS = [
    "一、研究背景与动机",
    "二、方法整体架构与核心机制",
    "三、实验结果",
    "四、核心结论",
    "五、创新点",
    "六、局限性",
]

FILLER = "这是一句没有数字的填充句，用来把篇幅撑到上限以上，验证裁剪逻辑是否生效。"
NUMERIC = "在 ImageNet 上准确率从 78.3% 提升到 81.9%，参数量 18.8M。"


def _make(n: int = 6) -> str:
    body = FILLER * n + NUMERIC
    return "\n\n".join(f"{h}\n{body}" for h in HEADS)


def test_short_detail_untouched():
    text = "\n\n".join(f"{h}\n短正文。" for h in HEADS)
    out, dropped = fit_detail(text)
    assert out == text
    assert dropped == 0


def test_long_detail_trimmed_within_limit():
    text = _make()
    assert len(text) > DETAIL_MAX
    out, dropped = fit_detail(text)
    assert len(out) <= DETAIL_MAX
    assert dropped > 0


def test_six_sections_survive():
    out, _ = fit_detail(_make())
    for h in HEADS:
        assert h in out


def test_numeric_sentence_kept():
    """数字句最难替代：先删没数字的，别把实验结果删掉。"""
    out, _ = fit_detail(_make())
    assert "81.9%" in out


def test_unexpected_structure_left_alone():
    """认不出六节结构就不动，避免把正常文本改坏。"""
    text = FILLER * 60
    assert len(text) > DETAIL_MAX
    out, dropped = fit_detail(text)
    assert out == text
    assert dropped == 0


def test_empty_detail():
    assert fit_detail("") == ("", 0)


def test_sections_end_with_period():
    """删完末句不能留下「；」收尾，否则读起来像被切断。"""
    text = "\n\n".join(
        f"{h}\n" + ("前半句没有数字的铺垫；" + NUMERIC) * 6 for h in HEADS
    )
    out, dropped = fit_detail(text)
    assert dropped > 0
    for blk in out.split("\n\n"):
        assert blk.rstrip()[-1] in "。！？", blk[-20:]

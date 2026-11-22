"""渲染集成测试（规格 §13）：文本 9 条、HTML 9 个卡片、降级文案在位。"""

import os

import yaml

from models import Paper
from render import html as render_html
from render import text as render_text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg():
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _mk(pid, ok=True):
    p = Paper(
        id=pid,
        title=f"Paper {pid} about transformer agents and diffusion",
        abstract="x",
        authors=["Alice", "Bob"],
        comment="Accepted at NeurIPS 2026",
        abs_url=f"http://arxiv.org/abs/{pid}v1",
        pdf_url=f"https://arxiv.org/pdf/{pid}v1",
        tldr="一句话总结，含具体数字：准确率提升 12%。",
        detail="详细解读。" * 60,
    )
    p.llm_ok = ok
    return p


def _data():
    return {
        "computer": [_mk(f"2610.0000{i}") for i in range(1, 4)],
        "embodied": [_mk(f"2610.1000{i}") for i in range(1, 4)],
        "aerospace": [_mk(f"2610.2000{i}") for i in range(1, 4)],
    }


def test_text_has_nine_entries():
    cfg = _cfg()
    text = render_text.render(_data(), "2026-10-24", cfg["publish"]["public_url"], cfg)
    assert text.count("详细解读 →") == 9
    assert "【论文日报 2026-10-24】" in text
    for name in ("计算机", "具身智能", "飞行器"):
        assert f"▍{name}" in text, f"缺少栏目 {name}"


def test_text_links_have_date_and_anchor():
    cfg = _cfg()
    text = render_text.render(_data(), "2026-10-24", cfg["publish"]["public_url"], cfg)
    assert "daily-2026-10-24.html#2610.00001" in text
    assert text.count("https://") >= 9, "链接必须带 https://，否则 QQ 不识别"


def test_html_has_nine_cards():
    cfg = _cfg()
    page = render_html.render(_data(), "2026-10-24", "", cfg["publish"]["public_url"],
                              render_html.TEMPLATE_PATH, cfg)
    assert page.count('<article id="') == 9
    assert "{{" not in page, "模板占位符没被替换干净"
    assert 'id="2610.00001"' in page, "锚点必须等于裸 ID"


def test_html_degrades_when_llm_fails():
    cfg = _cfg()
    data = _data()
    data["embodied"][1].llm_ok = False
    page = render_html.render(data, "2026-10-24", "", cfg["publish"]["public_url"],
                              render_html.TEMPLATE_PATH, cfg)
    assert "总结生成失败" in page

    text = render_text.render(data, "2026-10-24", cfg["publish"]["public_url"], cfg)
    assert "总结生成失败" in text


def test_empty_domain_degrades():
    cfg = _cfg()
    data = _data()
    data["aerospace"] = []
    text = render_text.render(data, "2026-10-24", cfg["publish"]["public_url"], cfg)
    assert "本领域今日抓取失败" in text


def test_prev_link():
    cfg = _cfg()
    page = render_html.render(_data(), "2026-10-24", "2026-10-23",
                              cfg["publish"]["public_url"],
                              render_html.TEMPLATE_PATH, cfg)
    assert "daily-2026-10-23.html" in page
    page2 = render_html.render(_data(), "2026-10-24", "", cfg["publish"]["public_url"],
                               render_html.TEMPLATE_PATH, cfg)
    assert "（无上一期）" in page2


def test_find_prev_date(tmp_path):
    d = tmp_path
    for name in ("daily-2026-10-20.html", "daily-2026-10-22.html", "daily-2026-10-24.html"):
        (d / name).write_text("x", encoding="utf-8")
    assert render_html.find_prev_date(str(d), "2026-10-24") == "2026-10-22"
    assert render_html.find_prev_date(str(d), "2026-10-20") == ""

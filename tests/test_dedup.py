"""去重：arXiv 的 id 带 v1/v2 后缀，不剥掉的话同一篇升级后会被当成新论文重推。

出错表现是"几天后重复推送"，肉眼极难发现，所以必须有测试。
"""

import os
import re

from sources.arxiv import _parse, _strip_version

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_arxiv.xml")

# 同一篇论文的 v1 和 v2（id 不同，abs_url 也不同）
TWO_VERSIONS = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2610.31670v1</id>
    <title>Same Paper</title>
    <summary>first version</summary>
    <published>2026-10-22T17:59:51Z</published>
    <arxiv:primary_category term="cs.RO"/>
    <category term="cs.RO"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2610.31670v2</id>
    <title>Same Paper</title>
    <summary>second version</summary>
    <published>2026-10-23T17:59:51Z</published>
    <arxiv:primary_category term="cs.RO"/>
    <category term="cs.RO"/>
  </entry>
</feed>
"""


def test_strip_version():
    assert _strip_version("2610.31670v1") == "2610.31670"
    assert _strip_version("2610.31670v12") == "2610.31670"
    assert _strip_version("2610.31670") == "2610.31670"


def test_two_versions_collapse_to_one():
    papers = _parse(TWO_VERSIONS)
    assert len(papers) == 2, "解析阶段应该两条都在"
    ids = {p.id for p in papers}
    assert len(ids) == 1, f"v1/v2 应剥成同一个裸 ID，实际 {ids}"
    # abs_url 保留原始版本号（链接要能打开原始页面）
    assert papers[0].abs_url != papers[1].abs_url


def test_fixture_ids_are_bare():
    """真实响应里的 id 全部不能有 vN 后缀。"""
    if not os.path.exists(FIXTURE):
        return  # fixture 缺失时不阻断其他测试
    with open(FIXTURE, encoding="utf-8") as f:
        papers = _parse(f.read())

    assert len(papers) == 100
    bad = [p.id for p in papers if re.search(r"v\d+$", p.id)]
    assert not bad, f"这些 id 没剥版本号：{bad[:5]}"
    assert len({p.id for p in papers}) == len(papers), "fixture 里出现了重复 id"


def test_fixture_abs_url_keeps_version():
    if not os.path.exists(FIXTURE):
        return
    with open(FIXTURE, encoding="utf-8") as f:
        papers = _parse(f.read())
    assert all("arxiv.org/abs/" in p.abs_url for p in papers)
    assert any(re.search(r"v\d+$", p.abs_url) for p in papers), "abs_url 应保留版本号"

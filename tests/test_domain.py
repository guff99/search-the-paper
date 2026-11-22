"""领域判定：cs.RO 同时属于具身智能和飞行器，规则顺序错了会导致某栏目长期空缺。

出错表现是"某栏目长期空缺"，不会报错，只能靠测试兜住。
"""

import os

import yaml

from filters.domain import assign_domain
from models import Paper

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg():
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _mk(title, cats, prim):
    return Paper(
        id="t", title=title, abstract="", authors=[],
        categories=cats, primary_category=prim,
    )


def test_rule1_single_domain_wins_over_keyword():
    """cs.CV 的无人机论文不能被 aerospace 抢走。"""
    cfg = _cfg()
    p = _mk("UAV Detection in the Wild", ["cs.CV"], "cs.CV")
    assert assign_domain(p, cfg["domains"]) == "computer"


def test_rule2_aerospace_keyword_on_conflict():
    cfg = _cfg()
    p = _mk("Aerial Manipulation with a UAV Arm", ["cs.RO"], "cs.RO")
    assert assign_domain(p, cfg["domains"]) == "aerospace"


def test_rule3_embodied_keyword_on_conflict():
    cfg = _cfg()
    p = _mk("Dexterous Manipulation via VLA Policy Learning", ["cs.RO"], "cs.RO")
    assert assign_domain(p, cfg["domains"]) == "embodied"


def test_rule4_fallback_by_config_order():
    """标题都不命中 → 按 config 书写顺序，cs.RO 落在 embodied 而不是 aerospace。"""
    cfg = _cfg()
    p = _mk("A Study of Nothing in Particular", ["cs.RO"], "cs.RO")
    assert assign_domain(p, cfg["domains"]) == "embodied"


def test_flu_dyn_goes_aerospace():
    cfg = _cfg()
    p = _mk("Wing Aerodynamics", ["physics.flu-dyn"], "physics.flu-dyn")
    assert assign_domain(p, cfg["domains"]) == "aerospace"


def test_only_one_domain_per_paper():
    cfg = _cfg()
    p = _mk("UAV Manipulation with VLA", ["cs.RO", "cs.CV"], "cs.RO")
    got = assign_domain(p, cfg["domains"])
    assert got in {"computer", "embodied", "aerospace"}

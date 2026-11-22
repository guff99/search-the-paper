"""精选补位：模型可能只给 2 条、可能给个不存在的 id、可能整个失败。

这几种情况都不能让某个栏目空着 —— 本文件在 T6 当场写，不留到最后。
"""

import os

import yaml

from models import Paper
from summarize import pick as pick_mod
from summarize.client import JsonError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cfg():
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _candidates(n=5):
    """按 score 降序的候选（top_n 的输出就是这样）。"""
    out = []
    for i in range(n):
        p = Paper(
            id=f"2610.0000{i + 1}",
            title=f"Paper {i + 1} about transformer agents",
            abstract="something",
        )
        p.score = float(n - i)
        out.append(p)
    return out


def test_model_gives_fewer_then_fill(monkeypatch):
    monkeypatch.setattr(
        pick_mod, "chat_json",
        lambda cfg, msgs, expect_keys: {
            "picked": [{"id": "2610.00001", "reason": "够新"}]
        },
    )
    got = pick_mod.pick("computer", _candidates(), 3, _cfg())
    assert len(got) == 3, "必须补齐到 quota"
    assert got[0].id == "2610.00001"
    assert got[0].picked_reason == "够新"
    assert got[1].id == "2610.00002", "补位要按 score 顺位取"
    assert got[2].id == "2610.00003"


def test_invalid_id_discarded(monkeypatch):
    monkeypatch.setattr(
        pick_mod, "chat_json",
        lambda cfg, msgs, expect_keys: {
            "picked": [{"id": "9999.99999", "reason": "编的"}]
        },
    )
    got = pick_mod.pick("computer", _candidates(), 3, _cfg())
    assert len(got) == 3
    assert all(p.id != "9999.99999" for p in got)


def test_id_with_version_suffix_still_matches(monkeypatch):
    monkeypatch.setattr(
        pick_mod, "chat_json",
        lambda cfg, msgs, expect_keys: {
            "picked": [{"id": "2610.00002v1", "reason": "带版本号"}]
        },
    )
    got = pick_mod.pick("computer", _candidates(), 3, _cfg())
    assert got[0].id == "2610.00002", "模型带回 v1 也要认出来"


def test_llm_fails_still_fills(monkeypatch):
    def boom(*a, **k):
        raise JsonError("模拟失败")

    monkeypatch.setattr(pick_mod, "chat_json", boom)
    got = pick_mod.pick("computer", _candidates(), 3, _cfg())
    assert len(got) == 3, "模型整个挂了也要凑满，不能让栏目空着"


def test_more_than_quota_is_truncated(monkeypatch):
    monkeypatch.setattr(
        pick_mod, "chat_json",
        lambda cfg, msgs, expect_keys: {
            "picked": [{"id": f"2610.0000{i}", "reason": "x"} for i in range(1, 6)]
        },
    )
    got = pick_mod.pick("computer", _candidates(), 3, _cfg())
    assert len(got) == 3


def test_empty_candidates(monkeypatch):
    assert pick_mod.pick("computer", [], 3, _cfg()) == []

"""publish/pages.py 的 remote 解析与 API 兜底单测（不发真实网络请求）。"""

import pytest

from publish import pages


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _FakeSession:
    """按 URL 返回预设响应，并记录所有写请求。"""

    def __init__(self):
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        if url.endswith("/git/ref/heads/main"):
            return _Resp(200, {"object": {"sha": "b" * 40}})
        if "/git/commits/" in url:
            return _Resp(200, {"tree": {"sha": "c" * 40}})
        if "/git/trees/" in url:
            return _Resp(200, {"tree": []})
        raise AssertionError(f"意外的 GET：{url}")

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", url, json))
        if url.endswith("/git/trees"):
            return _Resp(201, {"sha": "d" * 40})
        if url.endswith("/git/commits"):
            return _Resp(201, {"sha": "e" * 40})
        raise AssertionError(f"意外的 POST：{url}")

    def patch(self, url, json=None, timeout=None):
        self.calls.append(("PATCH", url, json))
        return _Resp(200, {})


@pytest.mark.parametrize("url,expected", [
    ("https://github.com/guff99/paper-radar-site.git",
     ("guff99", "paper-radar-site", "github.com")),
    ("https://github.com/guff99/paper-radar-site",
     ("guff99", "paper-radar-site", "github.com")),
    ("git@github.com:guff99/paper-radar-site.git",
     ("guff99", "paper-radar-site", "github.com")),
])
def test_parse_remote_github(url, expected):
    assert pages._parse_remote(url) == expected


@pytest.mark.parametrize("url", ["https://gitlab.com/a/b.git", "", "C:/local/repo"])
def test_parse_remote_non_github(url):
    assert pages._parse_remote(url) is None


def _fake_git(url="https://github.com/guff99/paper-radar-site.git", rev=""):
    def fn(repo_dir, *args, check=True):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        r = R()
        if args[:2] == ("remote", "get-url"):
            r.stdout = url
        elif args and args[0] == "rev-parse":
            r.stdout = rev
        return r
    return fn


def test_push_via_api_creates_commit(tmp_path, monkeypatch):
    site = tmp_path / "docs"
    site.mkdir()
    (site / "daily-2026-11-21.html").write_text("<html>hi</html>", encoding="utf-8")

    fake = _FakeSession()
    monkeypatch.setattr(pages, "_git", _fake_git(rev=""))  # 本地无该 blob → 走创建流程
    monkeypatch.setattr(pages, "_github_token", lambda host="github.com": "fake-token")
    import requests
    monkeypatch.setattr(requests, "Session", lambda: fake)

    ok = pages._push_via_api(str(tmp_path), "docs", "daily-2026-11-21.html",
                             "main", "2026-11-21")
    assert ok is True
    assert [c[0] for c in fake.calls] == ["POST", "POST", "PATCH"]
    tree_req = fake.calls[0][2]
    assert tree_req["base_tree"] == "c" * 40
    assert tree_req["tree"][0]["path"] == "docs/daily-2026-11-21.html"
    assert fake.calls[0][2]["tree"][0]["content"] == "<html>hi</html>"
    assert fake.calls[1][2] == {"message": "daily: 2026-11-21",
                                "tree": "d" * 40, "parents": ["b" * 40]}
    assert fake.calls[2][2] == {"sha": "e" * 40}


def test_push_via_api_skips_when_remote_matches(tmp_path, monkeypatch):
    site = tmp_path / "docs"
    site.mkdir()
    (site / "daily-2026-11-21.html").write_text("same", encoding="utf-8")

    class S(_FakeSession):
        def get(self, url, timeout=None):
            if url.endswith("/git/ref/heads/main"):
                return _Resp(200, {"object": {"sha": "b" * 40}})
            if "/git/commits/" in url:
                return _Resp(200, {"tree": {"sha": "c" * 40}})
            if url.endswith("/git/trees/" + "c" * 40):
                return _Resp(200, {"tree": [{"path": "docs", "type": "tree", "sha": "d" * 40}]})
            if url.endswith("/git/trees/" + "d" * 40):
                return _Resp(200, {"tree": [{"path": "daily-2026-11-21.html",
                                            "type": "blob", "sha": "SAME"}]})
            raise AssertionError(url)

    fake = S()
    monkeypatch.setattr(pages, "_git", _fake_git(rev="SAME"))
    monkeypatch.setattr(pages, "_github_token", lambda host="github.com": "fake-token")
    import requests
    monkeypatch.setattr(requests, "Session", lambda: fake)

    ok = pages._push_via_api(str(tmp_path), "docs", "daily-2026-11-21.html",
                             "main", "2026-11-21")
    assert ok is True
    assert fake.calls == []          # 内容一致，不该有任何写操作


def test_push_via_api_without_token(tmp_path, monkeypatch):
    monkeypatch.setattr(pages, "_git", _fake_git())
    monkeypatch.setattr(pages, "_github_token", lambda host="github.com": None)
    assert pages._push_via_api(str(tmp_path), "docs", "x.html", "main", "2026-11-21") is False

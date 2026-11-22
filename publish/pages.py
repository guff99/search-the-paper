"""发布到 GitHub Pages：写文件 + git commit + git push（git 不通时走 REST API）。

两条通道，同样的结果：
1. **git**（规格要求的主路径）：subprocess 调 git，push 失败时 stderr 原样打日志
   —— 绝大多数 push 失败都是凭证问题，stderr 会直接告诉你原因。
2. **REST API**（兜底）：有的网络环境只放行 api.github.com，github.com 的 git
   smart HTTP 会被代理 502 / TLS 掐断。Pages 只认远端内容，git 送不上去就用
   API 把同一个文件推上去，链接照样能点开。

凭证不落在配置文件里：API 用的 token 从 git 凭据管理器现取（git credential fill），
取不到就安静退回原来的重试逻辑。
"""

import os
import re
import subprocess


def _git(repo_dir: str, *args, check: bool = True):
    """跑一条 git 命令，返回 CompletedProcess。"""
    return subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=check,
    )


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _parse_remote(url: str):
    """从 origin URL 解析 (owner, repo, host)；不是 GitHub 就返回 None。"""
    m = re.search(r"github\.com[:/]+([^/]+)/([^/]+?)(?:\.git)?/?$", (url or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2), "github.com"


def _github_token(host: str = "github.com"):
    """取 GitHub token；取不到返回 None（不打印、不落盘）。

    优先读环境变量 GITHUB_TOKEN —— 云服务器 / 容器里没有 Git 凭据管理器，
    只能靠环境变量；本机没有这个变量时，再退回凭据管理器。
    """
    env_token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if env_token:
        return env_token
    r = subprocess.run(
        ["git", "credential", "fill"],
        input=f"protocol=https\nhost={host}\n\n",
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"},
    )
    m = re.search(r"^password=(.+)$", r.stdout, re.M)
    return m.group(1).strip() if m else None


def _remote_blob_sha(session, api: str, base_tree: str, site: str, filename: str) -> str:
    """在远端 tree 里找 site/filename 的 blob sha；找不到返回空串。"""
    try:
        root = session.get(f"{api}/git/trees/{base_tree}", timeout=30).json()
        for node in root.get("tree", []):
            if node.get("path") == site and node.get("type") == "tree":
                sub = session.get(f"{api}/git/trees/{node['sha']}", timeout=30).json()
                for n in sub.get("tree", []):
                    if n.get("path") == filename:
                        return n.get("sha", "")
    except Exception as e:  # 读不到就当远端没有，继续走创建流程
        print(f"[publish] 读取远端 tree 失败（不影响推送）：{e}")
    return ""


def _push_via_api(repo_dir: str, site_dir: str, filename: str,
                  branch: str, date: str) -> bool:
    """用 GitHub REST API 把一个文件推上去。成功返回 True，否则 False。"""
    try:
        import requests
    except ImportError:
        print("[publish] 未安装 requests，无法启用 API 兜底")
        return False

    url = _git(repo_dir, "remote", "get-url", "origin", check=False).stdout.strip()
    slug = _parse_remote(url)
    if not slug:
        print(f"[publish] remote 不是 GitHub，跳过 API 兜底：{url or '（无 remote）'}")
        return False
    owner, repo, host = slug

    token = _github_token(host)
    if not token:
        print("[publish] git 凭据里没有 GitHub token，跳过 API 兜底")
        return False

    site = site_dir.strip("/")
    path = os.path.join(repo_dir, site, filename)
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"[publish] 读不到待发布文件：{e}")
        return False

    api = f"https://api.github.com/repos/{owner}/{repo}"
    s = requests.Session()
    s.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    try:
        r = s.get(f"{api}/git/ref/heads/{branch}", timeout=30)
        if r.status_code != 200:
            print(f"[publish] 取远端分支失败：HTTP {r.status_code}")
            return False
        base_sha = r.json()["object"]["sha"]
        base_tree = s.get(f"{api}/git/commits/{base_sha}", timeout=30).json()["tree"]["sha"]

        # 远端已经有同样内容就不再重复提交（对应 git 的 diff --cached --quiet）
        local_blob = _git(repo_dir, "rev-parse", f"HEAD:{site}/{filename}",
                          check=False).stdout.strip()
        if local_blob and _remote_blob_sha(s, api, base_tree, site, filename) == local_blob:
            print("[publish] 远端内容已是最新，API 跳过")
            return True

        r = s.post(f"{api}/git/trees", json={
            "base_tree": base_tree,
            "tree": [{
                "path": f"{site}/{filename}",
                "mode": "100644",
                "type": "blob",
                "content": content,
            }],
        }, timeout=90)
        if r.status_code not in (200, 201):
            print(f"[publish] 创建 tree 失败：HTTP {r.status_code} {r.text[:200]}")
            return False
        tree_sha = r.json()["sha"]

        r = s.post(f"{api}/git/commits", json={
            "message": f"daily: {date}",
            "tree": tree_sha,
            "parents": [base_sha],
        }, timeout=60)
        if r.status_code not in (200, 201):
            print(f"[publish] 创建 commit 失败：HTTP {r.status_code} {r.text[:200]}")
            return False
        commit_sha = r.json()["sha"]

        r = s.patch(f"{api}/git/refs/heads/{branch}", json={"sha": commit_sha}, timeout=60)
        if r.status_code != 200:
            print(f"[publish] 更新分支失败：HTTP {r.status_code} {r.text[:200]}")
            return False

        print(f"[publish] API 发布成功：{owner}/{repo}@{branch} {commit_sha[:8]}")
        # 远端 commit 由 API 生成，与本地 commit 号不同（内容一致）。代理恢复后
        # 在站点仓库执行 `git fetch && git reset --hard origin/<branch>` 即可对齐历史。
        return True
    except Exception as e:
        print(f"[publish] API 兜底异常：{e}")
        return False


def publish(repo_dir: str, site_dir: str, filename: str, content: str,
            branch: str, date: str) -> None:
    """写 daily-*.html 到站点目录并推上去。

    先走 git，失败后尝试 GitHub REST API 兜底；都失败则重试，最终抛异常。
    """
    if not os.path.isdir(repo_dir):
        raise RuntimeError(f"站点仓库目录不存在：{repo_dir}")

    path = os.path.join(repo_dir, site_dir, filename)
    _write(path, content)
    print(f"[publish] 已写入 {path}（{len(content)} 字符）")

    last = None
    for attempt in range(1, 4):  # 首次 + 重试 2 次
        try:
            _git(repo_dir, "add", "-A")

            # 无变更就跳过 commit：git commit 空变更返回 1，
            # check=True 会把它当成凭证错误抛出来，非常误导
            probe = _git(repo_dir, "diff", "--cached", "--quiet", check=False)
            if probe.returncode == 0:
                print("[publish] 内容无变化，跳过 commit")
            else:
                _git(repo_dir, "commit", "-m", f"daily: {date}")

            r = _git(repo_dir, "push", "origin", branch, check=False)
            if r.returncode != 0:
                raise RuntimeError(f"git push 失败：{r.stderr.strip()[:500]}")
            print("[publish] push 成功")
            return
        except Exception as e:
            last = e
            print(f"[publish] 第 {attempt} 次 git 发布失败：{e}")
            # git 通道不通（代理只放行 api.github.com 等）时走 REST API
            if _push_via_api(repo_dir, site_dir, filename, branch, date):
                return

    raise RuntimeError(f"发布最终失败：{last}")


if __name__ == "__main__":
    # 只做体检：确认仓库目录在、git 能连上远端、API 兜底条件是否具备。
    # 不写任何文件、不改远端。
    import sys

    sys.path.insert(0, ".")
    from config import load

    cfg = load()
    repo = cfg["publish"]["repo_dir"]
    print("仓库目录:", repo, "存在" if os.path.isdir(repo) else "不存在！")
    if not os.path.isdir(repo):
        sys.exit(1)

    r = _git(repo, "status", "-sb", check=False)
    print("git status:", r.stdout.strip() or r.stderr.strip())
    r = _git(repo, "remote", "-v", check=False)
    print("remote:", r.stdout.strip() or "（无远端）")

    url = _git(repo, "remote", "get-url", "origin", check=False).stdout.strip()
    slug = _parse_remote(url)
    print("API 兜底:", f"可用（{slug[0]}/{slug[1]}）" if slug else "不可用（remote 不是 GitHub）")
    print("token   :", "已从 git 凭据读到" if _github_token() else "读不到")

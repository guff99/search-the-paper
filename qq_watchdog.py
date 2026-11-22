#!/usr/bin/env python3
"""QQ 通道看门狗。

由 systemd timer 每 15 分钟调用一次：
  1. 探 NapCat 的 /get_status
  2. 把结果写到 data/qq-status.json（控制台读它显示「QQ 在线/离线」）
  3. 掉线时在 GitHub 建一个 issue 告警（GitHub 会邮件通知仓库所有者），恢复后自动关掉

为什么告警走 GitHub Issue 而不是邮件：服务器上没有 SMTP 凭据，
而 GITHUB_TOKEN 已经在 .env 里（发布兜底也要用它），零新增配置。

用法：
    python qq_watchdog.py              正常检查
    python qq_watchdog.py --dry-run    只打印，不建 issue、不写状态文件
    python qq_watchdog.py --force      忽略「上次也离线」，强制重新建 issue
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from config import load  # noqa: E402

STATUS_FILE = os.path.join(ROOT, "data", "qq-status.json")
CST = timezone(timedelta(hours=8))
REPO = os.environ.get("ALERT_REPO", "guff99/search-the-paper")
TITLE_PREFIX = "⚠ QQ 机器人掉线"
CONSOLE_URL = os.environ.get("CONSOLE_URL", "http://8.136.5.160/")


def now_str() -> str:
    return datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")


def probe(cfg: dict) -> dict:
    """探一次 OneBot。返回 {online, account, error}。"""
    base = (cfg.get("qq") or {}).get("api_base", "").rstrip("/")
    tok = (cfg.get("qq") or {}).get("access_token", "")
    headers = {"Authorization": f"Bearer {tok}"} if tok else {}

    out = {"online": False, "account": None, "error": None}
    try:
        req = urllib.request.Request(f"{base}/get_status", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
        out["online"] = bool((d.get("data") or {}).get("online"))
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    if out["online"]:
        try:
            req = urllib.request.Request(f"{base}/get_login_info", headers=headers)
            with urllib.request.urlopen(req, timeout=8) as r:
                info = (json.loads(r.read()).get("data") or {})
            out["account"] = f"{info.get('nickname', '')}（{info.get('user_id', '')}）"
        except Exception:
            pass
    return out


def gh(method: str, path: str, body: dict | None = None):
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    if not tok:
        return None, "GITHUB_TOKEN 未设置"
    url = "https://api.github.com" + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return (json.loads(raw) if raw else {}), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode(errors='replace')[:200]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def find_open_issue():
    data, err = gh("GET", f"/repos/{REPO}/issues?state=open&per_page=50")
    if err:
        return None, err
    for it in data or []:
        if TITLE_PREFIX in (it.get("title") or ""):
            return it, None
    return None, None


def issue_body(status: dict) -> str:
    lines = [
        f"**检测时间**：{status['checked_at']}",
        f"**失败次数**：连续 {status['fail_count']} 次探测不到 QQ 在线",
        f"**探测地址**：`{status['api_base']}`",
    ]
    if status.get("error"):
        lines.append(f"**错误**：`{status['error']}`")
    lines += [
        "",
        "### 怎么修",
        "1. 打开控制台 " + f"{CONSOLE_URL}",
        "2. 顶部「QQ 通道」卡片会显示离线，点「登录二维码」",
        "3. 手机 QQ 扫码（二维码约 2 分钟一换，过期就点刷新）",
        "4. 恢复后本 issue 会被看门狗自动关闭",
        "",
        "> 自动告警：`qq_watchdog.py`，每 15 分钟检查一次。",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = load()
    res = probe(cfg)

    prev = {}
    try:
        with open(STATUS_FILE, encoding="utf-8") as f:
            prev = json.load(f) or {}
    except Exception:
        pass

    fail_count = 0 if res["online"] else int(prev.get("fail_count") or 0) + 1
    status = {
        "online": res["online"],
        "account": res["account"],
        "error": res["error"],
        "api_base": (cfg.get("qq") or {}).get("api_base", ""),
        "checked_at": now_str(),
        "fail_count": fail_count,
        "last_online_at": now_str() if res["online"] else prev.get("last_online_at"),
    }

    print(f"[watchdog] {status['checked_at']} online={status['online']} "
          f"account={status['account']} fail={fail_count}"
          + (f" error={status['error']}" if status["error"] else ""))

    if args.dry_run:
        print("[watchdog] --dry-run：不写状态、不动 issue")
        return

    os.makedirs(os.path.dirname(STATUS_FILE), exist_ok=True)
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)

    issue, err = find_open_issue()
    if err:
        print(f"[watchdog] 查 issue 失败：{err}")
        return

    if not res["online"]:
        if issue and not args.force:
            # 已有告警，只更新正文里的时间与次数，不刷评论
            gh("PATCH", f"/repos/{REPO}/issues/{issue['number']}",
               {"body": issue_body(status)})
            print(f"[watchdog] 已有告警 issue #{issue['number']}，已更新")
        else:
            data, err = gh("POST", f"/repos/{REPO}/issues", {
                "title": f"{TITLE_PREFIX}（{datetime.now(CST).strftime('%m-%d %H:%M')}）",
                "body": issue_body(status),
            })
            if err:
                print(f"[watchdog] 建 issue 失败：{err}")
            else:
                print(f"[watchdog] 已建告警 issue #{data.get('number')}")
    else:
        if issue:
            gh("POST", f"/repos/{REPO}/issues/{issue['number']}/comments",
               {"body": f"已恢复：{status['checked_at']} 探测到 {status['account']} 在线。"})
            gh("PATCH", f"/repos/{REPO}/issues/{issue['number']}", {"state": "closed"})
            print(f"[watchdog] 已恢复，关闭 issue #{issue['number']}")
        else:
            print("[watchdog] 在线，无需告警")


if __name__ == "__main__":
    main()

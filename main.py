"""编排：把采集 → 筛选 → 精选 → 总结 → 渲染 → 发布 → 推送 串起来。

三条硬要求（评审意见，别改）：
1. mark_pushed 必须在发群成功**之后** —— 反了，一次网络抖动就让这批论文永久丢失
2. 空数据必须早退 —— 没这个判断，周末会发布一张空 HTML 覆盖掉好页面
3. run_date 全流程唯一 —— 文件名、文案、去重记录、链接都用它

用法：
    python main.py                     正式全流程
    python main.py --dry-run           走完总结，跳过发布与推送（会真调 LLM）
    python main.py --ignore-history    忽略去重记录再跑一次
    python main.py --resend 2026-10-24 只重发 outbox/2026-10-24.txt
"""

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import datetime

# 第 0 行：Windows 控制台默认 GBK，打印 ▍ 这类字符会 UnicodeEncodeError
sys.stdout.reconfigure(encoding="utf-8")

import log_util  # noqa: E402

from config import enabled_domains, load  # noqa: E402
import store  # noqa: E402

from filters.domain import assign_domain  # noqa: E402
from filters.rank import top_n  # noqa: E402
from render import html as render_html  # noqa: E402
from render import text as render_text  # noqa: E402
from publish import pages  # noqa: E402
from sinks import qq  # noqa: E402
from sources.arxiv import fetch_all  # noqa: E402
from summarize.pick import pick  # noqa: E402
from summarize.write import write_all  # noqa: E402

TOP_N = 30  # 粗筛后送给 LLM 的候选数
PAGES_WAIT = 60  # Pages 构建延迟，push 完要等

OUTBOX = "outbox"
LLM_ALL_FAIL_MSG = "今日论文总结全部失败，请检查 API 配置与额度（日报未发送）"


def _outbox_path(name: str) -> str:
    os.makedirs(OUTBOX, exist_ok=True)
    return os.path.join(OUTBOX, name)


def _write_outbox(name: str, content: str) -> str:
    path = _outbox_path(name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _categories(cfg) -> list[str]:
    """config 里所有领域涉及的 arXiv 分类（去重，保持顺序）。"""
    cats = []
    for d in enabled_domains(cfg).values():
        for c in d.get("categories") or []:
            if c not in cats:
                cats.append(c)
    return cats


def run(dry_run: bool = False, ignore_history: bool = False,
        resend_date: str | None = None) -> None:
    log_util.setup()
    cfg = load()
    conn = store.init(cfg["store"]["db_path"])

    run_date = datetime.now().strftime("%Y-%m-%d")

    # --- 3b 只重发：不重抓、不重新总结、不发布 ---
    if resend_date:
        path = _outbox_path(f"{resend_date}.txt")
        if not os.path.exists(path):
            print(f"找不到 {path}")
            return
        with open(path, encoding="utf-8") as f:
            content = f.read()
        qq.send_group(
            cfg["qq"]["api_base"], cfg["qq"]["group_id"], content,
            token=cfg["qq"].get("access_token", ""),
        )
        return

    # --- 4 采集 ---
    try:
        papers = fetch_all(_categories(cfg), cfg["run"])
    except Exception as e:
        print(f"[main] 抓取失败：{e}")
        papers = []
    print(f"[main] 抓到 {len(papers)} 篇")

    # --- 5 领域分组 ---
    grouped = defaultdict(list)
    for p in papers:
        dom = assign_domain(p, enabled_domains(cfg))
        if dom:
            grouped[dom].append(p)

    # --- 6 去掉已经推过的 ---
    if not ignore_history:
        all_ids = [p.id for p in papers]
        keep = store.filter_unpushed(conn, all_ids)
        grouped = {k: [p for p in v if p.id in keep] for k, v in grouped.items()}
        total = sum(len(v) for v in grouped.values())
        print(f"[main] 去掉已推送的，剩 {total} 篇")

    # --- 7 空数据早退（周末 / key 没生效）---
    if sum(len(v) for v in grouped.values()) == 0:
        print("[main] 今日无新论文，不生成 HTML，不发群消息")
        return

    # --- 8 粗筛 + 精选 ---
    papers_by_domain: dict[str, list] = {}
    selected: list = []
    for key in enabled_domains(cfg):
        cands = top_n(grouped.get(key, []), cfg["domains"][key]["keywords"], TOP_N)
        if not cands:
            print(f"[main] {key}：无候选，该栏降级")
            papers_by_domain[key] = []
            continue
        got = pick(key, cands, cfg["domains"][key].get("quota", 3), cfg)
        papers_by_domain[key] = got
        selected.extend(got)
        print(f"[main] {key}：候选 {len(cands)} → 选出 {len(got)}")

    # --- 9 总结 ---
    write_all(selected, cfg)

    if selected and not any(p.llm_ok for p in selected):
        # 规格 §10：LLM 全部失败 → 不发日报，群里发一条错误提示
        print("[main] 总结全部失败")
        if not dry_run:
            qq.send_group(
                cfg["qq"]["api_base"], cfg["qq"]["group_id"], LLM_ALL_FAIL_MSG,
                token=cfg["qq"].get("access_token", ""),
            )
        return

    # --- 10 渲染 ---
    public_url = cfg["publish"]["public_url"]
    message = render_text.render(papers_by_domain, run_date, public_url, cfg)

    prev_date = render_html.find_prev_date(
        os.path.join(cfg["publish"]["repo_dir"], cfg["publish"]["site_dir"]), run_date
    )
    page = render_html.render(
        papers_by_domain, run_date, prev_date, public_url,
        render_html.TEMPLATE_PATH, cfg,
    )

    # --- 11 dry-run：只落本地，不对外产生副作用 ---
    if dry_run:
        path = _outbox_path(f"preview-{run_date}.html")
        render_html.write_file(page, path)
        print("\n" + "=" * 60)
        print(message)
        print("=" * 60)
        print(f"[main] dry-run 结束，HTML 已写到 {path}")
        return

    # --- 12 发布 ---
    filename = f"daily-{run_date}.html"
    try:
        pages.publish(
            cfg["publish"]["repo_dir"], cfg["publish"]["site_dir"], filename, page,
            cfg["publish"].get("branch", "main"), run_date,
        )
    except Exception as e:
        # 发布失败就不发消息：链接点开是 404，比不发更糟
        print(f"[main] 发布失败，不发群消息：{e}")
        p = _write_outbox(f"{run_date}.txt", message)
        print(f"[main] 文案已留存到 {p}，可手动补发")
        return

    # --- 13 等 Pages 构建（顺序不能反）---
    print(f"[main] 等 {PAGES_WAIT} 秒让 Pages 构建完成")
    time.sleep(PAGES_WAIT)

    # --- 14 推群 ---
    try:
        qq.send_group(
            cfg["qq"]["api_base"], cfg["qq"]["group_id"], message,
            token=cfg["qq"].get("access_token", ""),
        )
    except Exception as e:
        print(f"[main] 推送失败：{e}")
        p = _write_outbox(f"{run_date}.txt", message)
        print(f"[main] 文案已留存到 {p}，可用 --resend 补发")
        return

    # --- 15 只有走到这里才记账 ---
    store.mark_pushed(conn, selected, run_date)
    print(f"[main] 完成，已记账 {len(selected)} 篇")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="跳过发布与推送")
    ap.add_argument("--ignore-history", action="store_true", help="忽略已推送记录")
    ap.add_argument("--resend", metavar="YYYY-MM-DD", help="重发 outbox 里的某天文案")
    args = ap.parse_args()

    run(dry_run=args.dry_run, ignore_history=args.ignore_history,
        resend_date=args.resend)

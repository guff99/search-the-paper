"""已推送记录：SQLite。

为什么要记账：arXiv 的 72 小时窗口会重复抓到同一篇论文，
不记账的话同一篇会被反复推到群里。

用法（连接由 main.py 建一次，全流程共用）：
    conn = store.init(cfg["store"]["db_path"])
    ...
    conn.close()
"""

import os
import sqlite3
from datetime import datetime

# 表结构：id 是裸 ID（已剥 vN），PRIMARY KEY 天然去重
SCHEMA = """
CREATE TABLE IF NOT EXISTS pushed (
    id        TEXT PRIMARY KEY,
    date      TEXT,
    pushed_at TEXT
);
"""


def init(path: str) -> sqlite3.Connection:
    """建目录、建表，返回连接（不是 None —— 全流程共用这一个）。"""
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def filter_unpushed(conn: sqlite3.Connection, ids: list[str]) -> set[str]:
    """返回 ids 中**尚未推送过**的那些（集合）。

    实现细节：SQLite 的 IN 子句要按参数个数拼占位符，所以分批查。
    """
    if not ids:
        return set()

    unique_ids = list(dict.fromkeys(ids))
    pushed = set()

    # 每批 500 个，避免超长 SQL
    BATCH = 500
    for i in range(0, len(unique_ids), BATCH):
        batch = unique_ids[i : i + BATCH]
        marks = ",".join("?" * len(batch))
        rows = conn.execute(f"SELECT id FROM pushed WHERE id IN ({marks})", batch)
        pushed.update(r[0] for r in rows)

    return set(unique_ids) - pushed


def mark_pushed(conn: sqlite3.Connection, papers, date: str) -> None:
    """把一批 Paper 记为已推送。必须在发群成功之后调用。"""
    now = datetime.now().isoformat(timespec="seconds")
    rows = [(p.id, date, now) for p in papers]
    conn.executemany(
        "INSERT OR REPLACE INTO pushed (id, date, pushed_at) VALUES (?, ?, ?)", rows
    )
    conn.commit()


if __name__ == "__main__":
    # 冒烟：建库 → 标记 → 再查应为空
    import tempfile

    tmp = os.path.join(tempfile.gettempdir(), "paper-radar-store-smoke.db")
    if os.path.exists(tmp):
        os.remove(tmp)

    from models import Paper

    c = init(tmp)
    p = Paper(id="2610.31670", title="t", abstract="a")
    print("未推送：", filter_unpushed(c, ["2610.31670", "2610.00001"]))
    mark_pushed(c, [p], "2026-10-24")
    print("标记后仍未推送：", filter_unpushed(c, ["2610.31670", "2610.00001"]))
    print("表内容：", c.execute("SELECT * FROM pushed").fetchall())
    c.close()
    os.remove(tmp)
    print("store ok")

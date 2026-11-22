"""数据模型：全程序只流动一种东西 —— Paper。

为什么用 dataclass 而不是字典：
字典拼错键名不会报错，只会静默拿到 None，你要 debug 半天；
dataclass 写错字段名，Python 当场抛 AttributeError。
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Paper:
    # ---- 采集阶段填充 ----
    id: str                  # 裸 ID，如 "2610.31670"（已剥掉 v1/v2 后缀，去重主键）
    title: str
    abstract: str            # 已去掉换行
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    primary_category: str = ""   # 来自 <arxiv:primary_category>，领域判定规则 4 要用
    published: datetime | None = None   # 完整时间戳（UTC），窗口过滤与排序用
    date: str = ""           # "2026-10-22"，展示与文件名用
    comment: str = ""        # arXiv 的 comment 字段，常含 "Accepted at CoRL 2026"
    abs_url: str = ""
    pdf_url: str = ""

    # ---- 筛选阶段填充 ----
    domain: str = ""         # computer / embodied / aerospace
    score: float = 0.0
    picked_reason: str = ""  # 精选时模型给的理由

    # ---- 总结阶段填充 ----
    tldr: str = ""           # ≤100 字
    detail: str = ""         # 1200–1600 字（六节结构）
    llm_ok: bool = False     # 总结是否成功

    def short_title(self, n: int = 40) -> str:
        """超过 n 个字符就截断并加省略号。"""
        t = self.title.strip()
        return t if len(t) <= n else t[: n - 1] + "…"

    def authors_str(self, n: int = 3) -> str:
        """作者太多时只显示前 n 位。"""
        if not self.authors:
            return ""
        if len(self.authors) <= n:
            return ", ".join(self.authors)
        return ", ".join(self.authors[:n]) + " 等"

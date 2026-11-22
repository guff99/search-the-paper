"""领域判定：一篇论文只能进一个领域。

难点是 cs.RO 同时属于 embodied 和 aerospace —— 一篇讲无人机抓取的论文
两个领域都想要，必须有个确定的裁决顺序。

规则（严格按这个顺序，**顺序不能改**）：

1. 论文的分类只出现在一个领域里 → 直接归它（结束）
2. 出现在多个领域（cs.RO 冲突）且 aerospace 关键词命中标题 → aerospace
3. embodied 关键词命中标题 → embodied
4. 都不命中 → 按 config 里 domains 的书写顺序，第一个包含该论文主分类的领域

为什么规则 1 必须在最前：不先判"是否冲突"，一篇 cs.CV 的无人机检测论文
会因为标题含 UAV 被规则 2 抓走，从计算机池里彻底消失。
"""

from models import Paper


def _hit(text: str, keywords) -> bool:
    """大小写不敏感的子串匹配，命中任一关键词即为 True。"""
    low = (text or "").lower()
    for kw in keywords:
        if kw.lower() in low:
            return True
    return False


def _domains_of(categories, domains_cfg) -> list[str]:
    """哪些领域认领了这篇论文（按 config 书写顺序）。"""
    cats = set(categories or [])
    return [k for k, d in domains_cfg.items() if cats & set(d.get("categories") or [])]


def assign_domain(paper: Paper, domains_cfg: dict) -> str:
    """返回领域 key（computer / embodied / aerospace）；判不出来返回空串。"""
    if not domains_cfg:
        return ""

    claimed = _domains_of(paper.categories, domains_cfg)

    # 规则 1：只有一个领域认领
    if len(claimed) == 0:
        claimed = _domains_of([paper.primary_category], domains_cfg)
        if len(claimed) == 1:
            return claimed[0]
        return ""
    if len(claimed) == 1:
        return claimed[0]

    # 规则 2 / 3：冲突消解，只看标题（标题是作者浓缩过的，摘要里常有顺带提及）
    title = paper.title or ""
    if _hit(title, domains_cfg.get("aerospace", {}).get("keywords") or []):
        return "aerospace"
    if _hit(title, domains_cfg.get("embodied", {}).get("keywords") or []):
        return "embodied"

    # 规则 4：按书写顺序，第一个包含主分类的领域
    main_cat = paper.primary_category or (
        paper.categories[0] if paper.categories else ""
    )
    for key, d in domains_cfg.items():
        if main_cat in (d.get("categories") or []):
            return key

    return claimed[0] if claimed else ""


if __name__ == "__main__":
    # 手工构造 cs.RO 的 4 种情形，验证规则顺序
    from config import load

    cfg = load()

    def mk(title, cats, prim):
        return Paper(
            id="t", title=title, abstract="", authors=[],
            categories=cats, primary_category=prim,
        )

    cases = [
        ("cs.CV 的无人机检测（规则1，不该被 aerospace 抢走）",
         mk("UAV Detection in the Wild", ["cs.CV"], "cs.CV"), "computer"),
        ("cs.RO + 标题含 UAV（规则2）",
         mk("Aerial Manipulation with a UAV Arm", ["cs.RO"], "cs.RO"), "aerospace"),
        ("cs.RO + 标题含 manipulation（规则3）",
         mk("Dexterous Manipulation via VLA", ["cs.RO"], "cs.RO"), "embodied"),
        ("cs.RO + 标题都不命中（规则4 → embodied）",
         mk("A Study of Nothing in Particular", ["cs.RO"], "cs.RO"), "embodied"),
        ("physics.flu-dyn（规则1 → aerospace）",
         mk("Wing Aerodynamics", ["physics.flu-dyn"], "physics.flu-dyn"), "aerospace"),
    ]

    ok = True
    for desc, p, expect in cases:
        got = assign_domain(p, cfg["domains"])
        flag = "OK " if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(f"  [{flag}] {desc} → {got}（期望 {expect}）")

    print("domain rules ok" if ok else "domain rules FAILED")

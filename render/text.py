"""QQ 推送用的纯文本渲染。

三条硬规则（规格 §8.1）：
1. 三个领域顺序 = config.domains 的书写顺序
2. 链接带日期 + 锚点（不是首页）—— 否则昨天的消息今天点开会跳到完全不同的论文
3. 域名从 config 读，不硬编码

v1 一条消息发完（9 篇约 2000 字，远低于 4200 上限）。
"""

import os

from config import enabled_domains

TEMPLATE_PATH = os.path.join("templates", "qq.txt")

# 降级文案（规格 §8.1 / 计划 T8）
DOMAIN_FAIL = "本领域今日抓取失败"
PAPER_FAIL = "总结生成失败，点链接看原文"


def _section(domain_name: str, papers, date: str, public_url: str) -> str:
    """一个领域的那一段。"""
    lines = [f"▍{domain_name}"]

    if not papers:
        lines.append(DOMAIN_FAIL)
        return "\n".join(lines)

    for p in papers:
        lines.append(p.short_title(40))
        lines.append(PAPER_FAIL if not p.llm_ok else (p.tldr or PAPER_FAIL))
        lines.append(f"详细解读 → {public_url}daily-{date}.html#{p.id}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _overview(papers_by_domain: dict, cfg) -> str:
    """学「热点解码·论文汇」顶部 AI 摘要的骨架：分领域各一句速览。

    零额外 LLM 调用 —— 取每篇 tldr 的第一句压缩拼接，不重复下面的完整条目。
    """
    lines = []
    total = 0
    for key in enabled_domains(cfg):
        name = cfg["domains"][key].get("name", key)
        ps = papers_by_domain.get(key) or []
        total += len(ps)
        bits = []
        for p in ps:
            if not p.llm_ok or not p.tldr:
                continue
            first = p.tldr.strip().split("。", 1)[0].strip()
            if first:
                # tldr 由 write.txt 约束「第一句 ≤45 字」，直接用整句，别截成半截
                bits.append(first)
        lines.append(f"{name}：{'；'.join(bits)}。" if bits else f"{name}：今日无可用条目。")
    return "\n".join([f"▍今日概览 · 共 {total} 篇"] + lines)


def render(papers_by_domain: dict, date: str, public_url: str, cfg) -> str:
    """渲染整条 QQ 消息。papers_by_domain: {领域key: [Paper]}"""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        tpl = f.read()

    sections = []
    for key in enabled_domains(cfg):
        name = cfg["domains"][key].get("name", key)
        sections.append(
            _section(name, papers_by_domain.get(key) or [], date, public_url)
        )

    body = _overview(papers_by_domain, cfg) + "\n\n" + "\n\n".join(sections)
    text = tpl.replace("{{date}}", date).replace("{{sections}}", body)

    # v1 不切分（S1：split_message 是死代码），超长只记 warning
    limit = int(cfg["run"].get("max_message_chars", 3800))
    if len(text) > limit:
        print(f"[render] warning: 消息 {len(text)} 字，超过 max_message_chars={limit}")

    return text


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from config import load

    from models import Paper

    cfg = load()
    date = "2026-10-24"

    def mk(pid, title, tldr, ok=True):
        p = Paper(id=pid, title=title, abstract="", tldr=tldr, detail="x" * 300)
        p.llm_ok = ok
        return p

    demo = {
        "computer": [mk("2610.00001", "A Very Long Transformer Paper Title That Should Be Truncated Here", "把注意力换成线性核，在 ImageNet 上精度掉 0.3% 但速度快 4 倍。")],
        "embodied": [mk("2610.00002", "VLA for Dexterous Manipulation", "VLA（把视觉直接变成机器人动作的模型）在真机抓取上成功率从 41% 提到 78%。", ok=False)],
        "aerospace": [],
    }

    print(render(demo, date, cfg["publish"]["public_url"], cfg))

"""抓论文全文：arXiv 官方 HTML（LaTeXML）→ ar5iv 兜底 → 退回摘要。

为什么用 HTML 而不是 PDF：
- PDF 要额外依赖（pypdf/PyMuPDF），而本项目的依赖被限定在 requests + PyYAML；
- arXiv 从 2023 年底起给新论文生成 LaTeXML HTML，结构和正文都在，用标准库
  html.parser 就能抽干净；
- PDF 抽出来的文字常把公式、参考文献揉成一团，反而不如 HTML。

失败策略：任何一步失败都返回空串，调用方据此退回摘要。**绝不因为抓不到全文
就让整篇总结失败** —— 日报的价值在"稳定送达"，不是"每篇都完美"。
"""

import re
import time
from html.parser import HTMLParser

import requests

ARXIV_HTML = "https://arxiv.org/html/{pid}"
AR5IV_HTML = "https://ar5iv.labs.arxiv.org/html/{pid}"

UA = ("Mozilla/5.0 (compatible; paper-radar/1.0; "
      "+https://github.com/guff99/search-the-paper)")

# 抽出来的正文少于这个长度，基本可以断定是错误页/空壳，按失败处理
MIN_CHARS = 1500

# 这些标签整块丢掉；带这些 class 的容器也丢掉（arXiv 的页头页脚导航）
SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "header", "footer"}
SKIP_CLASSES = ("ltx_page_header", "ltx_page_footer", "ltx_page_navbar",
                "ltx_bibliography", "ltx_ERROR")
BLOCK_TAGS = {"p", "div", "section", "li", "tr", "h1", "h2", "h3", "h4", "h5",
              "h6", "br", "figcaption", "table", "blockquote", "dd", "dt"}
VOID_TAGS = {"br", "img", "hr", "input", "meta", "link"}

SESSION = requests.Session()
SESSION.trust_env = True   # 与 arxiv 抓取保持一致：走系统代理


class _TextExtractor(HTMLParser):
    """把 HTML 正文抽成纯文本：块级元素换行，公式取 alttext，丢掉脚本样式。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._stack: list[tuple[str, bool]] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        attrs_d = dict(attrs)
        cls = attrs_d.get("class") or ""
        if tag == "math":
            alt = (attrs_d.get("alttext") or "").strip()
            if alt and not self._skip:
                self.parts.append(f" {alt} ")
            self._skip += 1
            if tag not in VOID_TAGS:
                self._stack.append((tag, True))
            return

        skip = tag in SKIP_TAGS or any(k in cls for k in SKIP_CLASSES)
        if tag not in VOID_TAGS:
            self._stack.append((tag, skip))
        if skip:
            self._skip += 1
            return
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if not self._stack:
            return
        # 容错：向下找匹配的开标签，中间的直接弹掉
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                for _t, skipped in self._stack[i:]:
                    if skipped:
                        self._skip = max(0, self._skip - 1)
                del self._stack[i:]
                break
        if tag in BLOCK_TAGS and not self._skip:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        if data.strip():
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = raw.replace("\u00a0", " ")
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def extract(html: str) -> str:
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    return p.text()


def _strip_front_matter(text: str) -> str:
    """去掉正文之前的 arXiv 页面壳（标题重复、反馈表单、"Content selection saved" 之类）。

    正文开始的标志是 arXiv 自己的水印行：`arXiv:2611.26511v1 [cs.CV] 19 Nov 2026`。
    找不到就原样返回，不做激进裁剪。
    """
    m = re.search(r"(?m)^arXiv:\d{4}\.\d{4,5}v\d+\s+\[[^\]]+\]\s+\d{1,2}\s+\w+\s+\d{4}\s*$", text)
    if m:
        return text[m.end():].lstrip()
    return text


def _trim_references(text: str) -> str:
    """把参考文献之后的内容切掉 —— 几十条 bib 对写解读没用，纯烧 token。"""
    if len(text) < 2000:
        return text
    tail_start = int(len(text) * 0.6)
    window = text[tail_start:]
    m = None
    for m2 in re.finditer(r"\n(References|REFERENCES|参考文献)\s*\n", window):
        m = m2
    if m:
        return text[: tail_start + m.start()].rstrip()
    return text


def _get(session, url: str, timeout: float) -> str:
    try:
        r = session.get(url, timeout=timeout, headers={"User-Agent": UA})
        if r.status_code != 200:
            print(f"[fulltext]   {url.split('/')[2]} → HTTP {r.status_code}")
            return ""
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype and "<html" not in r.text[:500].lower():
            print(f"[fulltext]   {url.split('/')[2]} → 不是 HTML（{ctype}）")
            return ""
        return r.text
    except Exception as e:
        print(f"[fulltext]   {url.split('/')[2]} → {type(e).__name__}")
        return ""


def fetch(paper, scfg: dict, session=None) -> str:
    """抓一篇的全文（已清洗、已截断）。取不到返回空串。

    scfg 是 config 里的 summarize 段。
    """
    if not (scfg or {}).get("fulltext", True):
        return ""

    max_chars = int((scfg or {}).get("fulltext_max_chars", 40000))
    timeout = float((scfg or {}).get("fulltext_timeout", 30))
    sess = session or SESSION
    pid = getattr(paper, "id", "").strip()
    if not pid:
        return ""

    for tpl in (ARXIV_HTML, AR5IV_HTML):
        url = tpl.format(pid=pid)
        html = _get(sess, url, timeout)
        if not html:
            continue
        text = extract(html)
        if len(text) < MIN_CHARS:
            print(f"[fulltext]   {url.split('/')[2]} → 正文仅 {len(text)} 字，判为无效")
            continue

        text = _strip_front_matter(text)
        text = _trim_references(text)
        if len(text) > max_chars:
            # 不能简单地从开头截断：实验、结论、局限性都在论文后半段，
            # 砍掉尾部等于把最该读的部分丢了。改成「保头 + 保尾，省中间」。
            head_n = int(max_chars * 0.6)
            tail_n = max_chars - head_n
            head, tail = text[:head_n], text[-tail_n:]

            cut = head.rfind("\n\n")
            if cut > head_n * 0.75:
                head = head[:cut]
            cut = tail.find("\n\n")
            if 0 <= cut < tail_n * 0.25:
                tail = tail[cut:]

            text = (head.rstrip()
                    + "\n\n（中间部分因篇幅省略，以下直接跳到论文后半段）\n\n"
                    + tail.lstrip())

        print(f"[fulltext] {pid} 取到全文 {len(text)} 字（{url.split('/')[2]}）")
        return text

    print(f"[fulltext] {pid} 未取到全文，退回摘要")
    return ""


def fetch_all(papers, scfg: dict) -> dict:
    """批量抓，返回 {paper.id: 全文}。失败的键不放进去。"""
    out = {}
    for i, p in enumerate(papers, 1):
        t0 = time.time()
        text = fetch(p, scfg)
        if text:
            out[p.id] = text
        print(f"  [fulltext] {i}/{len(papers)} {p.id} "
              f"{'ok' if text else 'miss'} ({time.time() - t0:.1f}s)")
    return out

"""本地控制台：在浏览器里改 prompt、领域开关、每领域篇数、每日发送时间。

为什么不用 Flask/FastAPI：规格 §12 限定依赖只有 requests + PyYAML。
标准库 http.server 够用，而且启动零成本。

启动：
    python console.py            打开 http://127.0.0.1:8766/
    python console.py --no-open  只起服务，不自动开浏览器

安全：只绑 127.0.0.1，无鉴权 —— 它改的是本机几个文本文件，不对外暴露。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config.yaml")
PICK = os.path.join(ROOT, "prompts", "pick.txt")
WRITE = os.path.join(ROOT, "prompts", "write.txt")
HTML = os.path.join(ROOT, "templates", "console.html")
LOG = os.path.join(ROOT, "logs", "run.log")
OUTBOX = os.path.join(ROOT, "outbox")
QQ_STATUS = os.path.join(ROOT, "data", "qq-status.json")
NAPCAT_CACHE = os.environ.get("NAPCAT_CACHE", "/opt/napcat/cache")
SITE = os.path.join("C:/Users/guff/paper-radar-site", "docs")
TASK = "paper-radar-daily"
PORT = 8766

# 定时任务的两种后端：Windows 用 schtasks，Linux（云服务器）用 systemd timer
IS_WINDOWS = sys.platform.startswith("win")
SYSTEMD_TIMER = os.environ.get("PAPER_RADAR_TIMER", "paper-radar-daily.timer")
TIMER_FILE = f"/etc/systemd/system/{SYSTEMD_TIMER}"

# 论文来源候选：控制台下拉里列出来的 arXiv 分类（仍允许手填其他分类）
CATALOG = [
    {"group": "计算机", "items": [
        "cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.NE", "cs.RO", "cs.MA", "cs.IR",
        "cs.SE", "cs.HC", "cs.CR", "cs.DC", "cs.GR", "cs.SD", "cs.CE", "cs.SY"]},
    {"group": "电子电气", "items": ["eess.SY", "eess.SP", "eess.AS", "eess.IV"]},
    {"group": "物理", "items": [
        "physics.flu-dyn", "physics.comp-ph", "physics.ao-ph",
        "physics.data-an", "physics.app-ph"]},
    {"group": "数学与统计", "items": ["math.OC", "math.NA", "stat.ML"]},
]

# arXiv 分类：archive[.subclass]，如 cs.AI / eess.SY / physics.flu-dyn
CAT_RE = re.compile(r"^[a-z][a-z-]*(?:\.[A-Za-z][A-Za-z-]*)?$")
# 领域标识同时是 YAML key，限制成安全字符
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,23}$")

CFG_HEADER = "# 本文件由控制台 / 手工编辑，注释请保留\n"


class BadRequest(Exception):
    """客户端输入不合法：统一映射成 400，区别于服务端故障的 500。"""


# 写文件的进程内互斥锁。ThreadingHTTPServer 每个请求一个线程，
# 而 config.yaml 是「读-改-写」三步，必须整体串行化，否则两个请求
# 会基于同一份旧快照各写一遍，后写的把先写的覆盖掉。
# 用 RLock 是因为 _write() 自己也会取锁，而 update_domains() 需要
# 把「读 + 校验 + 写」包成一个临界区。
_WRITE_LOCK = threading.RLock()


# ---------- 文本工具 ----------

def _read(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return default


def _write(path: str, text: str) -> None:
    """先写同目录下的唯一临时文件，fsync 后原子替换。

    为什么不用 `path + ".tmp"`：临时文件名固定时，两个并发请求会同时
    打开同一个 .tmp，Windows 上后到的那个直接 PermissionError（实测 5 并发
    挂 3 个）。mkstemp 保证每次拿到独占的新文件名，os.replace 在同一卷上
    是原子的 —— 要么看到旧文件，要么看到完整的新文件，不会读到半截。
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with _WRITE_LOCK:
        fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".",
                                   suffix=".swap", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())   # 先落盘再改名，避免断电留下 0 字节目标文件
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def _load_cfg() -> dict:
    import yaml
    return yaml.safe_load(_read(CONFIG)) or {}


# ---------- config.yaml 定点修改（保留注释） ----------

def _domains_span(lines: list[str]):
    """返回 domains: 段的行区间 [start, end)，排除 run/llm 等同样 2 空格缩进的其他段。"""
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^domains:\s*$", line):
            start = i
            continue
        if start is not None and re.match(r"^[A-Za-z#]", line):
            return start, i
    return (start, len(lines)) if start is not None else (None, None)


def _domain_blocks(lines: list[str], start: int, end: int):
    """在 domains 段内找每个领域块：返回 [(key, block_start, block_end)]。"""
    heads = []
    for i in range(start + 1, end):
        m = re.match(r"^  ([A-Za-z0-9_]+):\s*$", lines[i])
        if m:
            heads.append((m.group(1), i))
    blocks = []
    for idx, (key, i) in enumerate(heads):
        stop = heads[idx + 1][1] if idx + 1 < len(heads) else end
        blocks.append((key, i, stop))
    return blocks


def update_domains(items, removed=None) -> str:
    """整块保存领域：支持改名、改来源/篇数/关键词/启用、新增、删除。

    写法上仍然是「先整体校验 → 改内存 lines → 一次性落盘」：
    任何一项不合法都在动笔之前抛错，config.yaml 保持原样。
    新增的领域追加在 domains 段末尾，删除的领域整块移除，已有领域的注释一律保留。
    """
    if not isinstance(items, list) or not items:
        raise BadRequest("至少要保留一个领域")
    if removed is None:
        removed = []
    if not isinstance(removed, list) or any(not isinstance(x, str) for x in removed):
        raise BadRequest("removed 必须是领域标识的数组")

    import yaml

    with _WRITE_LOCK:
        text = _read(CONFIG)
        lines = text.splitlines(keepends=True)
        start, end = _domains_span(lines)
        if start is None:
            raise RuntimeError("config.yaml 里找不到 domains: 段")

        known = {b[0] for b in _domain_blocks(lines, start, end)}
        current = (yaml.safe_load(text) or {}).get("domains") or {}

        for k in removed:
            if k not in known:
                raise BadRequest(f"领域 {k} 不存在，无法删除")

        # ---- 第一遍：只校验，不碰 lines ----
        pending, fresh, seen = [], [], set()
        for item in items:
            if not isinstance(item, dict):
                raise BadRequest("domains 的每一项都必须是对象")

            key = item.get("key")
            if not isinstance(key, str) or not KEY_RE.match(key):
                raise BadRequest(
                    f"领域标识只能是 2-24 位小写字母/数字/下划线（收到 {key!r}）")
            if key in seen:
                raise BadRequest(f"领域 {key} 重复出现")
            if key in removed:
                raise BadRequest(f"领域 {key} 同时出现在保存与删除列表里")
            seen.add(key)
            is_new = key not in known

            name = item.get("name")
            if name is not None:
                if not isinstance(name, str):
                    raise BadRequest(f"{key}: 名称必须是字符串")
                name = name.strip()
                if not name or len(name) > 20:
                    raise BadRequest(f"{key}: 名称需 1-20 个字")
                if re.search(r"[:#\[\],\n\r\t]", name):
                    raise BadRequest(f"{key}: 名称不能包含 : # [ ] , 等字符")
            elif is_new:
                raise BadRequest(f"{key}: 新领域必须填名称")

            categories = item.get("categories")
            cleaned = None
            if categories is not None:
                if not isinstance(categories, list) or not categories:
                    raise BadRequest(f"{key}: 论文来源不能为空，至少选一个分类")
                cleaned = []
                for c in categories:
                    if not isinstance(c, str):
                        raise BadRequest(f"{key}: 分类格式不对 → {c}（示例：cs.AI、eess.SY）")
                    c = c.strip()
                    if not c:
                        continue
                    if not CAT_RE.match(c):
                        raise BadRequest(f"{key}: 分类格式不对 → {c}（示例：cs.AI、eess.SY）")
                    if c not in cleaned:
                        cleaned.append(c)
                if not cleaned:
                    raise BadRequest(f"{key}: 论文来源不能为空")
            elif is_new:
                raise BadRequest(f"{key}: 新领域至少选一个论文来源")

            keywords = item.get("keywords")
            kws = None
            if keywords is not None:
                if not isinstance(keywords, list):
                    raise BadRequest(f"{key}: 关键词必须是数组")
                kws = []
                for w in keywords:
                    if not isinstance(w, str):
                        raise BadRequest(f"{key}: 关键词格式不对 → {w}")
                    w = w.strip()
                    if not w:
                        continue
                    if len(w) > 40 or re.search(r"[,\[\]\n\r:]", w):
                        raise BadRequest(
                            f"{key}: 关键词不能含逗号/方括号/冒号，且不超过 40 字（收到 {w}）")
                    if w not in kws:
                        kws.append(w)

            quota = item.get("quota")
            if quota is not None:
                # bool 是 int 的子类，True 会被悄悄当成 1；浮点也不接受
                if isinstance(quota, bool) or not isinstance(quota, int):
                    raise BadRequest(f"{key}: 篇数必须是 1-10 的整数（收到 {quota!r}）")
                if not 1 <= quota <= 10:
                    raise BadRequest(f"{key}: 篇数必须在 1-10 之间（收到 {quota}）")

            enabled = item.get("enabled")
            if enabled is not None and not isinstance(enabled, bool):
                raise BadRequest(f"{key}: enabled 必须是 true 或 false")

            if is_new:
                fresh.append({
                    "key": key,
                    "name": name,
                    "categories": cleaned or [],
                    "keywords": kws or [],
                    "quota": quota if quota is not None else 3,
                    "enabled": True if enabled is None else enabled,
                })
            else:
                pending.append((key, cleaned, quota, enabled, name, kws))

        # ---- 第二遍：算「改完之后」是否还有启用中的领域 ----
        effective = {k: bool((v or {}).get("enabled", True))
                     for k, v in current.items() if k not in removed}
        for key, _c, _q, enabled, _n, _k in pending:
            if enabled is not None:
                effective[key] = enabled
        for d in fresh:
            effective[d["key"]] = d["enabled"]
        if not any(effective.values()):
            raise BadRequest("至少要启用一个领域")

        # ---- 第三遍：删 ----
        for k in removed:
            block = next((b for b in _domain_blocks(lines, start, end) if b[0] == k), None)
            if block is None:   # 第一遍校验过，理论不可达
                raise RuntimeError(f"{k}: 领域块在删除阶段丢失")
            del lines[block[1]:block[2]]
            start, end = _domains_span(lines)

        # ---- 第四遍：改 ----
        for key, cleaned, quota, enabled, name, kws in pending:
            block = next((b for b in _domain_blocks(lines, start, end) if b[0] == key), None)
            if block is None:
                raise RuntimeError(f"{key}: 领域块在写入阶段丢失")
            _, b_start, b_end = block

            if name is not None:
                hit = False
                for i in range(b_start + 1, b_end):
                    if re.match(r"^    name:\s*", lines[i]):
                        lines[i] = f"    name: {name}\n"
                        hit = True
                        break
                if not hit:
                    lines.insert(b_start + 1, f"    name: {name}\n")

            if cleaned is not None:
                hit = False
                for i in range(b_start + 1, b_end):
                    if re.match(r"^    categories:\s*", lines[i]):
                        lines[i] = f"    categories: [{', '.join(cleaned)}]\n"
                        hit = True
                        break
                if not hit:
                    raise RuntimeError(f"{key}: config.yaml 里找不到 categories 行")

            if kws is not None:
                # 内容没变就别重写：keywords 可能是跨多行的 flow 序列，
                # 无谓重写会把排版压成一行（YAML 等价，但 diff 很脏）。
                # 注意这里只能跳过「关键词」这一项，不能 continue ——
                # 后面的 quota / enabled 还要继续写。
                cur_kw = [str(x) for x in ((current.get(key) or {}).get("keywords") or [])]
                if cur_kw != kws:
                    hit = False
                    for i in range(b_start + 1, b_end):
                        if re.match(r"^    keywords:\s*", lines[i]):
                            # 关键词可能写成多行 flow 序列，要连同续行一起替换
                            j = i
                            while j < b_end and not lines[j].rstrip("\n").rstrip().endswith("]"):
                                j += 1
                            lines[i:j + 1] = [f"    keywords: [{', '.join(kws)}]\n"]
                            hit = True
                            break
                    if not hit:
                        raise RuntimeError(f"{key}: config.yaml 里找不到 keywords 行")

            if quota is not None:
                hit = False
                for i in range(b_start + 1, b_end):
                    if re.match(r"^    quota:\s*", lines[i]):
                        lines[i] = f"    quota: {quota}\n"
                        hit = True
                        break
                if not hit:
                    raise RuntimeError(f"{key}: config.yaml 里找不到 quota 行")

            if enabled is not None:
                flag = "true" if enabled else "false"
                hit = False
                for i in range(b_start + 1, b_end):
                    if re.match(r"^    enabled:\s*", lines[i]):
                        lines[i] = f"    enabled: {flag}\n"
                        hit = True
                        break
                if not hit:
                    lines.insert(b_end, f"    enabled: {flag}\n")
            # 每插/删一行，后续区间会整体移动；重新扫描
            start, end = _domains_span(lines)

        # ---- 第五遍：增（追加到 domains 段最后一个非空行之后）----
        for d in fresh:
            start, end = _domains_span(lines)
            ins = end
            while ins > start + 1 and not lines[ins - 1].strip():
                ins -= 1
            lines[ins:ins] = [
                f"  {d['key']}:\n",
                f"    name: {d['name']}\n",
                f"    categories: [{', '.join(d['categories'])}]\n",
                f"    keywords: [{', '.join(d['keywords'])}]\n",
                f"    quota: {d['quota']}\n",
                f"    enabled: {'true' if d['enabled'] else 'false'}\n",
            ]

        _write(CONFIG, "".join(lines))
    return f"已保存（{len(items)} 个领域）"

def _systemd_query() -> dict:
    """读 systemd timer 里的 OnCalendar，返回与 Windows 分支同构的字典。"""
    out = {"exists": False, "time": None, "wake": False,
           "catch_up": False, "backend": "systemd", "active": False}
    try:
        with open(TIMER_FILE, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return out

    m = re.search(r"^OnCalendar=\S*\s*(\d{2}):(\d{2}):\d{2}\s*$", text, re.M)
    if m:
        out["time"] = f"{m.group(1)}:{m.group(2)}"
    out["exists"] = True
    # Persistent=true 等价于 Windows 的「错过则尽快启动」
    out["catch_up"] = bool(re.search(r"^Persistent=true\s*$", text, re.M))
    try:
        r = subprocess.run(["systemctl", "is-active", SYSTEMD_TIMER],
                           capture_output=True, text=True, timeout=8)
        out["active"] = r.stdout.strip() == "active"
    except Exception:
        pass
    return out


def _systemd_set(hhmm: str) -> str:
    """改 OnCalendar 行 → daemon-reload → 重启 timer。需要 root。"""
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        raise RuntimeError(
            f"修改 systemd timer 需要 root 权限（当前 uid={os.geteuid()}）。"
            f"请用 sudo 执行，或手工改 {TIMER_FILE} 后 systemctl daemon-reload"
        )
    try:
        with open(TIMER_FILE, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise RuntimeError(f"读不到 {TIMER_FILE}：{e}")

    new_text, n = re.subn(r"^OnCalendar=.*$", f"OnCalendar=*-*-* {hhmm}:00",
                          text, flags=re.M)
    if n == 0:
        raise RuntimeError(f"{TIMER_FILE} 里没有 OnCalendar 行，未做修改")

    tmp = TIMER_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, TIMER_FILE)

    for args in (["daemon-reload"], ["restart", SYSTEMD_TIMER]):
        r = subprocess.run(["systemctl"] + args, capture_output=True,
                           text=True, timeout=20)
        if r.returncode != 0:
            raise RuntimeError((r.stdout or "") + (r.stderr or ""))
    return f"已设为每天 {hhmm}（systemd timer 已重启）"


def query_schedule() -> dict:
    if not IS_WINDOWS:
        return _systemd_query()
    try:
        r = subprocess.run(["schtasks", "/Query", "/TN", TASK, "/XML"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except OSError as e:
        # 沙箱/受限环境会直接拒绝创建进程；不要让整个页面跟着 500
        return {"exists": False, "time": None, "wake": False, "catch_up": False,
                "error": f"无法调用 schtasks（{e.__class__.__name__}）：{e}"}
    if r.returncode != 0:
        return {"exists": False, "time": None, "wake": False, "catch_up": False}
    xml = r.stdout
    m = re.search(r"<StartBoundary>([^<]+)</StartBoundary>", xml)
    hhmm = None
    if m:
        t = re.search(r"T(\d{2}):(\d{2})", m.group(1))
        hhmm = f"{t.group(1)}:{t.group(2)}" if t else None
    return {
        "exists": True,
        "time": hhmm,
        "wake": "<WakeToRun>true</WakeToRun>" in xml,
        "catch_up": "<StartWhenAvailable>true</StartWhenAvailable>" in xml,
    }


def set_schedule(hhmm: str) -> str:
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", hhmm or ""):
        raise RuntimeError("时间格式应为 HH:MM，例如 07:30")

    if not IS_WINDOWS:
        return _systemd_set(hhmm)

    python = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python):
        python = sys.executable
    # 用 XML 建任务：能指定 WorkingDirectory，并勾上「唤醒计算机」「错过则尽快启动」
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-11-22T{hhmm}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python}</Command>
      <Arguments>main.py</Arguments>
      <WorkingDirectory>{ROOT}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    xml_path = os.path.join(ROOT, ".tmp", "task.xml")
    os.makedirs(os.path.dirname(xml_path), exist_ok=True)
    with open(xml_path, "w", encoding="utf-16") as f:
        f.write(xml)

    try:
        r = subprocess.run(["schtasks", "/Create", "/XML", xml_path, "/TN", TASK, "/F"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace")
    except OSError as e:
        raise RuntimeError(
            f"无法调用 schtasks（{e.__class__.__name__}）。"
            f"可复制这条命令到普通 PowerShell 手动执行：\n"
            f'schtasks /Create /XML "{xml_path}" /TN {TASK} /F'
        )
    if r.returncode != 0:
        raise RuntimeError((r.stdout or "") + (r.stderr or ""))
    return f"已设为每天 {hhmm}"


# ---------- 统计与列表 ----------

def stats() -> dict:
    cfg = _load_cfg()
    today = time.strftime("%Y-%m-%d")
    pushed = 0
    try:
        import sqlite3
        db = os.path.join(ROOT, cfg.get("store", {}).get("db_path", "data/pushed.db"))
        conn = sqlite3.connect(db)
        pushed = conn.execute("select count(*) from pushed").fetchone()[0]
        conn.close()
    except Exception:
        pass
    pub = cfg.get("publish") or {}
    site_dir = os.path.join(pub.get("repo_dir", ""), pub.get("site_dir", "docs"))
    return {
        "today": today,
        "pushed_total": pushed,
        "has_today_html": os.path.exists(os.path.join(OUTBOX, f"preview-{today}.html")),
        "site_online": os.path.isdir(site_dir),
        "group_id": (cfg.get("qq") or {}).get("group_id"),
        "public_url": pub.get("public_url"),
    }


def outbox_files() -> list[dict]:
    out = []
    if not os.path.isdir(OUTBOX):
        return out
    for name in sorted(os.listdir(OUTBOX), reverse=True):
        if not name.endswith(".html"):
            continue
        p = os.path.join(OUTBOX, name)
        m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        out.append({
            "name": name,
            "date": m.group(1) if m else "",
            "size": os.path.getsize(p),
            "mtime": time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(p))),
        })
    return out


def log_tail(lines: int = 120) -> list[str]:
    try:
        with open(LOG, encoding="utf-8", errors="replace") as f:
            return f.read().splitlines()[-lines:]
    except OSError:
        return []


# ---------- QQ 通道状态 ----------

def qq_status() -> dict:
    """实时探一次 NapCat；探不到就退回看门狗写的缓存，并给出二维码是否可拿。"""
    cfg = _load_cfg()
    qq = cfg.get("qq") or {}
    api = (qq.get("api_base") or "").rstrip("/")
    token = qq.get("access_token") or ""
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    out = {
        "online": False,
        "account": None,
        "checked_at": None,
        "api_base": api,
        "source": "live",
        "error": None,
        "fail_count": 0,
    }

    cached = {}
    try:
        with open(QQ_STATUS, encoding="utf-8") as f:
            cached = json.load(f) or {}
    except Exception:
        pass

    try:
        req = urllib.request.Request(api + "/get_status", headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read())
        out["online"] = bool((data.get("data") or {}).get("online"))
        out["checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if out["online"]:
            try:
                req = urllib.request.Request(api + "/get_login_info", headers=headers)
                with urllib.request.urlopen(req, timeout=3) as r:
                    info = json.loads(r.read()).get("data") or {}
                out["account"] = f"{info.get('nickname', '')}（{info.get('user_id', '')}）"
            except Exception:
                pass
    except Exception as e:
        # 连不上：用缓存说明「上次是什么时候看到的」，别让页面一片空白
        out["online"] = False
        out["error"] = type(e).__name__
        out["checked_at"] = cached.get("checked_at")
        out["source"] = "cache"
        out["fail_count"] = cached.get("fail_count", 0)

    qr = os.path.join(NAPCAT_CACHE, "qrcode.png")
    if os.path.isfile(qr):
        out["qr_age_sec"] = int(time.time() - os.path.getmtime(qr))
    else:
        out["qr_age_sec"] = None
    return out


# ---------- HTTP ----------

class Handler(BaseHTTPRequestHandler):
    server_version = "paper-radar-console/1.0"

    def log_message(self, fmt, *args):  # 别把访问日志刷到终端
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _body(self) -> dict:
        """解析 JSON 请求体；不合法就抛 BadRequest（→400）。

        以前解析失败返回 {}，调用方无法区分「空对象」和「根本没解析成功」，
        /api/prompts 就这样把两个文件写成了空串。这里改成 fail-closed。
        """
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise BadRequest("请求体为空")
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as e:
            raise BadRequest(f"请求体不是合法 JSON：{e}")
        if not isinstance(data, dict):
            raise BadRequest("请求体必须是 JSON 对象")
        return data

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = _read(HTML)
            if not html:
                return self._send(500, "console.html 缺失".encode(), "text/plain; charset=utf-8")
            return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/state":
            try:
                cfg = _load_cfg()
                return self._json({
                    "prompts": {"pick": _read(PICK), "write": _read(WRITE)},
                    "domains": [
                        {
                            "key": k,
                            "name": v.get("name", k),
                            "quota": v.get("quota", 3),
                            "enabled": v.get("enabled", True),
                            "categories": v.get("categories", []),
                            "keyword_list": v.get("keywords", []),
                        }
                        for k, v in (cfg.get("domains") or {}).items()
                    ],
                    "catalog": CATALOG,
                    "schedule": query_schedule(),
                    "stats": stats(),
                    "qq": qq_status(),
                    "history": outbox_files()[:12],
                    "logs": log_tail(80),
                })
            except Exception as e:
                return self._json({"error": f"{e.__class__.__name__}: {e}"}, 500)
        if path == "/api/logs":
            return self._json({"lines": log_tail(200)})
        if path == "/api/qq":
            return self._json(qq_status())
        if path in ("/qq/qrcode", "/qq/qrcode.png"):
            # 只暴露登录二维码这一张图，不暴露缓存目录里的其他东西
            fp = os.path.join(NAPCAT_CACHE, "qrcode.png")
            if os.path.isfile(fp):
                with open(fp, "rb") as f:
                    return self._send(200, f.read(), "image/png")
            return self._send(404, b"no qrcode", "text/plain; charset=utf-8")
        if path.startswith(("/history/", "/outbox/")):
            # 直接预览本地日报（不暴露目录，只允许简单文件名）
            name = path.split("/", 2)[2]
            if re.match(r"^[A-Za-z0-9_.-]+$", name):
                fp = os.path.join(OUTBOX, name)
                if os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        return self._send(200, f.read(), "text/html; charset=utf-8")
            return self._send(404, b"not found", "text/plain; charset=utf-8")
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/prompts", "/api/domains", "/api/schedule", "/api/run"):
            return self._json({"error": "not found"}, 404)
        try:
            data = self._body()   # 解析失败在这里就 400，后续逻辑不会拿到空字典
            if path == "/api/prompts":
                pick = data.get("pick")
                write = data.get("write")
                # 两个字段必须同时给且非空：只给一个说明调用方有问题，
                # 沿用「缺失即空串」的写法会把另一个 prompt 清空（不可逆）。
                # 校验放在任何 _write 之前，失败时一个字节都不碰。
                for name, val in (("pick", pick), ("write", write)):
                    if not isinstance(val, str) or not val.strip():
                        raise BadRequest(f"{name} 必须是非空字符串，本次未写入任何文件")
                with _WRITE_LOCK:   # 两个文件一起替换，避免与并发请求交叉
                    _write(PICK, pick)
                    _write(WRITE, write)
                return self._json({"ok": True, "message": "两个 prompt 已保存"})
            if path == "/api/domains":
                msg = update_domains(data.get("domains"), data.get("removed"))
                return self._json({"ok": True, "message": msg})
            if path == "/api/schedule":
                msg = set_schedule(data.get("time", ""))
                return self._json({"ok": True, "message": msg})
            if path == "/api/run":
                # 后台跑一次 dry-run，不发布不推群
                python = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
                if not os.path.exists(python):
                    python = sys.executable
                out = open(os.path.join(ROOT, "logs", "console-run.log"), "a",
                           encoding="utf-8")
                subprocess.Popen([python, "main.py", "--dry-run"], cwd=ROOT,
                                 stdout=out, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                return self._json({"ok": True, "message": "已在后台启动 dry-run，日志见 logs/console-run.log"})
        except BadRequest as e:
            return self._json({"ok": False, "message": str(e)}, 400)
        except Exception as e:
            return self._json({"ok": False, "message": str(e)}, 500)
        self._json({"error": "not found"}, 404)


def main():
    no_open = "--no-open" in sys.argv
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://127.0.0.1:{PORT}/"
    print(f"[console] 控制台已启动：{url}")
    print("[console] Ctrl+C 停止")
    if not no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[console] 已停止")


if __name__ == "__main__":
    main()

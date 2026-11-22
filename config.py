"""配置加载：全项目唯一读取 config.yaml 的地方。

设计原则：
- 其他模块不自己读文件，参数由 main.py 传进去。
- 必填项缺失就在启动时报错退出，不要跑到一半才炸。
"""

import os
import sys

import yaml

# (一级键, 二级键) —— 任何一项缺失都直接退出
REQUIRED = [
    ("llm", "base_url"),
    ("llm", "model"),
    ("llm", "api_key_env"),
    ("qq", "api_base"),
    ("qq", "group_id"),
    ("publish", "repo_dir"),
    ("publish", "site_dir"),
    ("publish", "public_url"),
    ("store", "db_path"),
]

# run 段的默认值：配置里没写就用这些
RUN_DEFAULTS = {
    "window_hours": 72,
    "per_category_limit": 100,
    "timeout_sec": 40,
    "retries": 3,
    "request_interval": 3.0,
    "max_message_chars": 3800,
}

# summarize 段的默认值：默认把全文喂给模型，抓不到再退回摘要
SUMMARIZE_DEFAULTS = {
    "fulltext": True,            # 是否抓论文全文
    "fulltext_max_chars": 40000,  # 全文截断上限（字符），约 1.2 万 token
    "fulltext_timeout": 30,      # 单篇全文抓取超时（秒）
    "timeout_sec": 150,          # 单次总结调用超时；长输入比默认 40 秒慢得多
}


def _get(cfg: dict, section: str, key: str):
    """安全地取嵌套值，取不到返回 None。"""
    return (cfg.get(section) or {}).get(key)


def load(path: str = "config.yaml") -> dict:
    """读配置、校验、填默认值。出错直接 sys.exit(1)。"""
    if not os.path.exists(path):
        print(f"[config] 找不到配置文件：{path}")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # 1) 必填项校验
    missing = [f"{s}.{k}" for s, k in REQUIRED if _get(cfg, s, k) in (None, "")]
    if missing:
        print("[config] 缺少必填配置项：")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

    # 2) public_url 必须以 / 结尾
    #    少一个斜杠会拼出 https://x.github.iopaper-radar/daily-... 这种不可点的链接，
    #    而且程序不会报错，只会在群里表现为"链接点不开"。
    url = cfg["publish"]["public_url"]
    if not url.endswith("/"):
        print(f"[config] publish.public_url 必须以 / 结尾，当前是：{url}")
        sys.exit(1)

    # 3) API Key 从环境变量取，不落在配置文件里
    env_name = cfg["llm"]["api_key_env"]
    api_key = os.environ.get(env_name, "")
    if not api_key:
        print(f"[config] 环境变量 {env_name} 未设置（这是 LLM 的 API Key）")
        sys.exit(1)
    cfg["llm"]["api_key"] = api_key

    # 4) run 段填默认值
    run = cfg.setdefault("run", {})
    for k, v in RUN_DEFAULTS.items():
        run.setdefault(k, v)

    # 5) summarize 段填默认值
    sm = cfg.setdefault("summarize", {})
    for k, v in SUMMARIZE_DEFAULTS.items():
        sm.setdefault(k, v)

    return cfg


def domain_names(cfg: dict) -> list[str]:
    """按 config 里的书写顺序返回领域 key —— 顺序即渲染顺序。"""
    return list((cfg.get("domains") or {}).keys())


def enabled_domains(cfg: dict) -> dict:
    """只返回启用的领域（没写 enabled 视为启用），保持书写顺序。

    控制台可以逐个开关领域。关掉的领域必须**整体退出**：
    不参与抓取分类、不参与领域判定（否则它的 cs.RO 会先把论文抢走、
    然后又没人处理），也不参与渲染。
    """
    return {k: v for k, v in (cfg.get("domains") or {}).items()
            if v.get("enabled", True)}


if __name__ == "__main__":
    c = load()
    print("配置加载成功")
    print("  领域顺序：", " → ".join(f"{k}({v['name']})" for k, v in c["domains"].items()))
    print("  每领域篇数：", [v["quota"] for v in c["domains"].values()])
    print("  数据库：", c["store"]["db_path"])
    print("  Pages：", c["publish"]["public_url"])

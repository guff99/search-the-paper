"""极简 LLM 客户端：requests 直接 POST，不引入 SDK。

为什么不用 openai/ dashscope SDK：SDK 把请求体藏起来了，
出问题你只能看到一句 "BadRequest"。裸 requests 能打印出真实的
URL、请求体、返回码 —— 排查 401/404 时差一个数量级。
"""

import json
import time

import requests

# 与 sources/arxiv.py 保持一致：让 requests 读系统/环境变量里的代理
SESSION = requests.Session()
SESSION.trust_env = True


class JsonError(Exception):
    """模型返回的不是能用的 JSON（缺字段 / 解析失败 / 重试后仍然不行）。"""


def chat(cfg, messages, temperature: float = 0.3, max_retries: int = 2,
         timeout: float | None = None) -> str:
    """发一次对话，返回模型输出的文本。

    cfg：config.load() 的返回值（需要 llm.base_url / llm.model / llm.api_key）。
    timeout：单独指定超时；不传就退回 run.timeout_sec（摘要长输入需要更宽）。
    """
    llm = cfg["llm"]
    url = llm["base_url"].rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {llm['api_key']}",
        "Content-Type": "application/json",
    }
    body = {
        "model": llm["model"],
        "messages": messages,
        "temperature": temperature,
    }
    timeout = float(timeout or cfg["run"].get("timeout_sec", 40))

    last = None
    for i in range(max_retries):
        t0 = time.time()
        try:
            resp = SESSION.post(url, headers=headers, json=body, timeout=timeout)
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            text = data["choices"][0]["message"]["content"]
            usage = (data.get("usage") or {}).get("total_tokens", "?")
            print(f"    [llm] {time.time() - t0:.1f}s, tokens={usage}")
            return text
        except Exception as e:
            last = e
            print(f"    [llm] 第 {i + 1} 次失败：{e}")
            if i < max_retries - 1:
                time.sleep(2)

    raise last


def _strip_fence(text: str) -> str:
    """去掉 ```json ... ``` 围栏和首尾空白。"""
    t = (text or "").strip()
    if t.startswith("```"):
        # 去掉首行的 ```json
        first_nl = t.find("\n")
        if first_nl != -1:
            t = t[first_nl + 1 :]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[: -3]
    return t.strip()


def chat_json(cfg, messages, expect_keys: list[str],
              timeout: float | None = None) -> dict:
    """让模型返回 JSON，解析成 dict。

    expect_keys：返回的 dict **必须**含这些键，缺任一个就当失败走重试。
    （不是"有这些键就行"，是"少一个都不行"。）

    失败重试 1 次（追加一句"只输出 JSON"），仍失败抛 JsonError。
    """
    attempts = [
        list(messages),
        list(messages) + [{"role": "user", "content": "请只输出 JSON，不要任何解释、不要代码块。"}],
    ]

    last = None
    for i, msgs in enumerate(attempts):
        try:
            raw = chat(cfg, msgs, max_retries=1, timeout=timeout)
            data = json.loads(_strip_fence(raw))
            if not isinstance(data, dict):
                raise JsonError(f"返回的不是对象：{type(data)}")
            missing = [k for k in expect_keys if k not in data]
            if missing:
                raise JsonError(f"缺字段 {missing}")
            return data
        except JsonError as e:
            last = e
            print(f"    [llm] JSON 校验失败（第 {i + 1} 次）：{e}")
        except Exception as e:
            last = e
            print(f"    [llm] JSON 解析失败（第 {i + 1} 次）：{e}")
        if i == 0:
            time.sleep(1)

    raise JsonError(f"JSON 调用最终失败：{last}")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, ".")
    from config import load

    cfg = load()
    print("模型:", cfg["llm"]["model"])
    print("返回:", chat(cfg, [{"role": "user", "content": "回一句话证明你活着"}]))

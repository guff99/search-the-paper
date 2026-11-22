"""QQ 群推送：NapCat 的 OneBot 11 HTTP 接口，只用一个 send_group_msg。

    POST {api_base}/send_group_msg
    {"group_id": 123456789, "message": "..."}

group_id 必须是 int（OneBot 协议要求），不要转成字符串。
"""

import time

import requests

# trust_env=False：NapCat 在本机 127.0.0.1，绝不能绕代理出去
# （一旦走了系统代理，localhost 请求会被代理拒绝或超时）。
SESSION = requests.Session()
SESSION.trust_env = False


def send_group(api_base: str, group_id, message: str, token: str = "",
               timeout: int = 20, retries: int = 2) -> None:
    """发一条群消息。失败重试 2 次，仍失败抛异常（由 main 写 outbox）。"""
    url = api_base.rstrip("/") + "/send_group_msg"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = {"group_id": int(group_id), "message": message}

    last = None
    for attempt in range(1, retries + 2):
        try:
            r = SESSION.post(url, headers=headers, json=body, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            # OneBot 11：HTTP 200 也可能是业务失败，要看 retcode
            if data.get("retcode", 0) != 0:
                raise RuntimeError(
                    f"retcode={data.get('retcode')} {data.get('message') or data.get('wording') or ''}"
                )
            print(f"[qq] 已发送（{len(message)} 字符）")
            return
        except Exception as e:
            last = e
            print(f"[qq] 第 {attempt} 次发送失败：{e}")
            if attempt <= retries:
                time.sleep(3)

    raise RuntimeError(f"QQ 推送最终失败：{last}")


if __name__ == "__main__":
    # python -m sinks.qq "要发的消息"   （不传消息就只做配置体检）
    import sys

    sys.path.insert(0, ".")
    from config import load

    cfg = load()
    api_base = cfg["qq"]["api_base"]
    group_id = cfg["qq"]["group_id"]
    token = cfg["qq"].get("access_token", "")

    if group_id == 0:
        print("config.yaml 的 qq.group_id 还是 0 —— 先填群号再发")
        sys.exit(1)

    msg = " ".join(sys.argv[1:]).strip()
    if not msg:
        print(f"用法：python -m sinks.qq \"消息内容\"（当前 api_base={api_base}, group_id={group_id}）")
        sys.exit(0)

    send_group(api_base, group_id, msg, token=token)

"""日志：同时写文件与打印到终端。

为什么单独一个文件：计划任务在后台跑，终端看不见，
logs/run.log 是失败时唯一的线索。

两条路都进同一个文件：
1. `logging.*` —— 规格要求的方式（FileHandler + encoding="utf-8"）。
2. 现有的大量 `print(...)` —— 业务代码里 90 多处都用 print，逐个改既费事
   又容易改坏输出格式，所以把 sys.stdout / sys.stderr 套一层 Tee 分流到文件。
   这样无论用 logging 还是 print，run.log 都能拿到完整现场。
"""

import logging
import os
import sys

LOG_DIR = "logs"
LOG_FILE = "run.log"


class _Tee:
    """把写入同时转发给终端和日志文件。

    只做转发，不改变 print 的行为；写入后立即 flush，
    保证计划任务被强杀时也不丢最后几行。
    """

    def __init__(self, stream, fileobj):
        self._stream = stream
        self._file = fileobj

    def write(self, data):
        try:
            self._stream.write(data)
        except Exception:
            pass
        try:
            self._file.write(data)
            self._file.flush()
        except Exception:
            pass
        return len(data)

    def flush(self):
        for target in (self._stream, self._file):
            try:
                target.flush()
            except Exception:
                pass

    def isatty(self):
        return bool(getattr(self._stream, "isatty", lambda: False)())

    def fileno(self):
        return self._stream.fileno()

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")

    def __getattr__(self, name):
        # 未实现的方法/属性一律透传给原始流（如 buffer、closed）
        return getattr(self._stream, name)


def setup(level=logging.INFO) -> None:
    """配置 root logger，并让 print 也落到 logs/run.log。

    Windows 控制台默认 GBK，直接 print 中文/特殊符号会 UnicodeEncodeError，
    所以先把 stdout 改成 utf-8（允许重复调用）。
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass  # 已经是 utf-8 或不支持 reconfigure，忽略

    log_path = os.path.join(LOG_DIR, LOG_FILE)

    # 1) logging —— StreamHandler 绑的是当前（尚未包装的）终端流，
    #    后面的 Tee 只接管 print，所以不会和 FileHandler 重复写。
    handlers = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,  # 重复调用时覆盖旧配置，而不是静默失效
    )

    # 2) print -> 终端 + 文件（避免重复包装）
    if not isinstance(sys.stdout, _Tee):
        fp = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = _Tee(sys.stdout, fp)
    if not isinstance(sys.stderr, _Tee):
        fp_err = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stderr = _Tee(sys.stderr, fp_err)


if __name__ == "__main__":
    setup()
    logging.info("日志自检：logging 通道 → 中文 ▍ 与特殊符号都能写")
    print("日志自检：print 通道 → 特殊符号 ▍【】也能写")
    print("log_util ok —— 两条通道都应出现在 logs/run.log")

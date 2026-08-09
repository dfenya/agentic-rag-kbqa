"""LLM 调用重试工具 —— 带指数退避的重试封装"""

import time


def retry_invoke(fn, *args, _delays=(1.0, 3.0), **kwargs):
    """最多 3 次尝试（1 次主调用 + 2 次重试），间隔 1s / 3s"""
    last_err = None
    for delay in (None,) + _delays:
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if delay is not None:
                time.sleep(delay)
    raise last_err

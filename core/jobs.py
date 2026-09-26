"""
轻量后台任务管理器（v1.7.0）。

设计动机：Streamlit 脚本是单线程阻塞执行的——一个按钮触发 spinner 时，
整个页面无法响应其它操作。本模块把耗时工作（全文抓取、图表抓取等）放进
守护线程执行，UI 主线程通过轮询读取进度，从而实现：

- 全文摘要与图表解析同时进行，互不阻塞；
- 批量任务在后台跑，页面始终可操作，完成后自动刷新展示。

线程安全约定：
- 任务函数只能通过 update() 修改自己的 job 记录，绝不触碰 st.* 与
  st.session_state（Streamlit 会话状态非线程安全）；
- 结果放在 job["result"] 里，由 UI 主线程在 fragment 轮询中"消费"
  （consume）并写入 session_state，再触发整页刷新渲染。
"""
import threading
import time
import traceback
import uuid

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
# 最多保留多少条已结束任务（防止长时间运行内存无限增长）
_MAX_FINISHED = 30


def _gc():
    """清理过旧的已结束任务（持锁调用）"""
    finished = [(j["created"], jid) for jid, j in _jobs.items() if j["status"] in ("done", "error")]
    if len(finished) <= _MAX_FINISHED:
        return
    finished.sort()
    for _, jid in finished[: len(finished) - _MAX_FINISHED]:
        _jobs.pop(jid, None)


def start(name: str, fn, key: str = "", *args, **kwargs) -> str:
    """
    启动一个后台任务。

    fn 的第一个参数固定为 job dict，可通过 jobs.update(job, progress=..., note=...)
    汇报进度；返回值会作为结果存入 job["result"]。
    key 用于去重：同 key 的任务运行中时再次 start 会返回 ""。
    """
    if key and is_running(key):
        return ""
    jid = uuid.uuid4().hex[:8]
    job = {
        "id": jid,
        "name": name,
        "key": key,
        "status": "running",
        "progress": 0.0,
        "note": "准备中…",
        "result": None,
        "error": None,
        "trace": None,
        "consumed": False,
        "created": time.time(),
        "finished": None,
    }
    with _lock:
        _jobs[jid] = job
        _gc()

    def run():
        try:
            res = fn(job, *args, **kwargs)
            with _lock:
                job["result"] = res
                job["status"] = "done"
                job["progress"] = 1.0
                job["finished"] = time.time()
        except Exception as e:  # noqa: BLE001 —— 后台线程兜底，异常进任务记录
            with _lock:
                job["status"] = "error"
                job["error"] = f"{e.__class__.__name__}: {e}"
                job["trace"] = traceback.format_exc()[-900:]
                job["finished"] = time.time()

    threading.Thread(target=run, daemon=True, name=f"medlit-job-{jid}").start()
    return jid


def update(job: dict, progress: float | None = None, note: str | None = None):
    """任务线程内汇报进度（progress 0.0~1.0）"""
    with _lock:
        if progress is not None:
            job["progress"] = max(0.0, min(1.0, float(progress)))
        if note is not None:
            job["note"] = note


def is_running(key: str) -> bool:
    with _lock:
        return any(
            j.get("key") == key and j["status"] in ("running",)
            for j in _jobs.values()
        )


def snapshot() -> list[dict]:
    """全部任务快照（UI 主线程只读展示用）"""
    with _lock:
        return [dict(j) for j in sorted(_jobs.values(), key=lambda x: x["created"])]


def consume(jid: str):
    """
    UI 主线程领取已完成任务的结果：标记 consumed 防止重复消费，返回 job dict。
    """
    with _lock:
        j = _jobs.get(jid)
        if not j or j.get("consumed") or j["status"] not in ("done", "error"):
            return None
        j["consumed"] = True
        return dict(j)


def clear_finished():
    with _lock:
        for jid in [jid for jid, j in _jobs.items() if j["status"] in ("done", "error")]:
            _jobs.pop(jid, None)

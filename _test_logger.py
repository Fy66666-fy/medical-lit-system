"""日志系统自测（v2.4.0）

覆盖：目录创建 / 级别写入 / span 耗时与异常记录 / tail 读取 / 关闭开关 / 写入失败不拖垮主流程。
临时目录通过 MEDLIT_DATA_DIR 注入，不污染真实数据目录。
"""
import importlib
import os
import sys
import tempfile
import time
import unittest

_TMP = tempfile.mkdtemp(prefix="medlit_log_")
os.environ["MEDLIT_DATA_DIR"] = _TMP
os.environ["MEDLIT_LOG"] = "1"
os.environ.pop("MEDLIT_LOG_LEVEL", None)

sys.path.insert(0, ".")

from core import logger  # noqa: E402


class TestLogger(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        logger.setup("test")

    def test_log_dir_created(self):
        self.assertTrue(os.path.isdir(logger.LOG_DIR))
        self.assertTrue(logger.LOG_DIR.startswith(_TMP))

    def test_log_file_created(self):
        files = os.listdir(logger.LOG_DIR)
        self.assertTrue(any(f.startswith("app_") and f.endswith(".log") for f in files))

    def test_write_and_read(self):
        marker = f"MARKER_{int(time.time() * 1000)}"
        logger.info(marker)
        time.sleep(0.05)
        self.assertIn(marker, logger.tail(80))

    def test_error_with_exception(self):
        try:
            raise ValueError("boom_value_error")
        except ValueError as e:
            logger.error("测试异常记录", e)
        time.sleep(0.05)
        txt = logger.tail(80)
        self.assertIn("测试异常记录", txt)
        self.assertIn("boom_value_error", txt)

    def test_span_success(self):
        with logger.span("span_ok_case"):
            time.sleep(0.01)
        time.sleep(0.05)
        txt = logger.tail(80)
        self.assertIn("→ span_ok_case", txt)
        self.assertIn("← span_ok_case 完成", txt)

    def test_span_exception_reraises(self):
        with self.assertRaises(RuntimeError):
            with logger.span("span_fail_case"):
                raise RuntimeError("inner_boom")
        time.sleep(0.05)
        txt = logger.tail(80)
        self.assertIn("✗ span_fail_case 失败", txt)
        self.assertIn("inner_boom", txt)

    def test_excepthook_installed(self):
        logger.install_excepthook()
        self.assertIsNotNone(sys.excepthook)

    def test_tail_when_no_file(self):
        """日志文件不存在时返回提示文案而非抛异常"""
        import core.logger as lg

        orig = lg.LOG_DIR
        try:
            lg.LOG_DIR = os.path.join(_TMP, "nonexistent")
            out = lg.tail(10)
            self.assertIsInstance(out, str)
        finally:
            lg.LOG_DIR = orig

    def test_write_never_raises(self):
        """日志目录被破坏时，写入必须静默失败而不是抛异常"""
        import core.logger as lg

        orig_dir = lg.LOG_DIR
        try:
            lg.LOG_DIR = os.path.join(_TMP, "\0invalid")
            lg.info("这条应被静默忽略")
            lg.error("这条也应被静默忽略", ValueError("x"))
            with lg.span("异常目录下的 span"):
                pass
        except Exception as e:  # 任何异常都算失败
            self.fail(f"日志写入不应抛异常，实际抛出：{e!r}")
        finally:
            lg.LOG_DIR = orig_dir

    def test_disabled_switch(self):
        """MEDLIT_LOG=0 时完全关闭：不创建文件、不写入"""
        os.environ["MEDLIT_LOG"] = "0"
        try:
            lg = importlib.reload(logger)
            self.assertFalse(lg._ENABLED)
            lg.setup("test")
            self.assertFalse(lg._ready)
            lg.info("不应写入任何内容")
            self.assertNotIn("不应写入任何内容", lg.tail(50))
        finally:
            # reload 会重置模块状态（_ready=False），需重新 setup 恢复可用，
            # 并清掉旧 handler 避免重复写两份日志
            os.environ["MEDLIT_LOG"] = "1"
            lg2 = importlib.reload(logger)
            for h in list(lg2._logger.handlers):
                lg2._logger.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
            lg2.setup("test")


if __name__ == "__main__":
    unittest.main(verbosity=2)

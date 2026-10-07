"""NCBI API Key 自测：速率切换 + 参数自动注入 + 不泄露密钥。

背景：NCBI 对每个 IP 的限速，无 key 约 3 req/s、有 key 约 10 req/s。
这是「多人同时检索」时唯一的硬天花板，所以 key 的接入必须可靠且不泄漏。
"""
import io
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp(prefix="medlit_ncbi_")
os.environ["MEDLIT_DATA_DIR"] = _TMP
os.environ["MEDLIT_HTTP_LOG"] = "0"
os.environ.pop("NCBI_API_KEY", None)
os.environ.pop("MEDLIT_SCOPE", None)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import http  # noqa: E402

EUTILS = "eutils.ncbi.nlm.nih.gov"
PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(("  [OK]   " if cond else "  [FAIL] ") + name + (f" · {detail}" if detail else ""))


class _FakeResp:
    status_code = 200
    content = b"ok"

    def raise_for_status(self):
        return None


class _FakeSession:
    """拦截请求，只记录参数，不发真实网络请求。"""

    def __init__(self):
        self.calls = []
        self.headers = {}

    def request(self, method, url, params=None, data=None, json=None,
                headers=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        return _FakeResp()


def main() -> int:
    print("\n[1] 速率切换")
    base = http.host_delay_for(EUTILS)
    check("无 key 时为 3 req/s 档", abs(base - 0.36) < 1e-6, f"{base}s")
    check("无 key 时 ncbi_rate_limit 一致", abs(http.ncbi_rate_limit() - 0.36) < 1e-6)

    ok = http.configure_ncbi("TESTKEY-123456")
    check("configure_ncbi 返回启用成功", ok is True)
    fast = http.host_delay_for(EUTILS)
    check("有 key 时降到 10 req/s 档", abs(fast - 0.10) < 1e-6, f"{fast}s")
    check("rate_limit 同步", abs(http.ncbi_rate_limit() - 0.10) < 1e-6)
    check("速率提升约 3.3 倍", 3.4 < base / fast < 3.7, f"{base / fast:.2f}x")
    check("其他域名不受影响", abs(http.host_delay_for("europepmc.org") - 0.34) < 1e-6)

    print("\n[2] 参数自动注入")
    fake = _FakeSession()
    orig = http._session
    http._session = lambda: fake
    try:
        http.get(f"https://{EUTILS}/entrez/eutils/esearch.fcgi",
                 params={"db": "pubmed", "term": "cancer"})
        p = fake.calls[-1]["params"]
        check("esearch 自动带上 api_key", p.get("api_key") == "TESTKEY-123456", str(p))
        check("原有参数未被覆盖", p.get("term") == "cancer")

        http.get(f"https://{EUTILS}/entrez/eutils/efetch.fcgi", params={"db": "pubmed"})
        check("efetch 同样自动注入",
              fake.calls[-1]["params"].get("api_key") == "TESTKEY-123456")

        # 调用方自己传了 api_key 时不应被强改
        http.get(f"https://{EUTILS}/x", params={"api_key": "CALLER"})
        check("调用方显式传入时优先", fake.calls[-1]["params"]["api_key"] == "CALLER")

        http.get("https://api.unpaywall.org/v2/10.1/x", params={"email": "a@b.c"},
                 raise_for_status=False)
        check("非 NCBI 域名不注入 key",
              "api_key" not in (fake.calls[-1]["params"] or {}))

        http.get(f"https://{EUTILS}/x")
        check("params 为 None 时也能安全注入",
              (fake.calls[-1]["params"] or {}).get("api_key") == "TESTKEY-123456")
    finally:
        http._session = orig

    print("\n[3] 关闭与恢复")
    http.configure_ncbi(None)
    check("清空后回到 3 req/s 档", abs(http.host_delay_for(EUTILS) - 0.36) < 1e-6)
    check("清空后 key 读取为空", http.ncbi_api_key() == "")

    print("\n[4] 环境变量兜底")
    os.environ["NCBI_API_KEY"] = "ENVKEY-654321"
    check("环境变量被读取", http.ncbi_api_key() == "ENVKEY-654321")
    check("环境变量下 rate_limit 为 10 req/s 档",
          abs(http.ncbi_rate_limit() - 0.10) < 1e-6)
    os.environ.pop("NCBI_API_KEY", None)

    print("\n[5] 密钥不外泄")
    http.configure_ncbi("SECRET-ABCDEF")
    fake2 = _FakeSession()
    orig2 = http._session
    http._session = lambda: fake2
    try:
        http.get(f"https://{EUTILS}/x", params={"db": "pubmed"})
    finally:
        http._session = orig2
    stats_txt = str(http.stats())
    check("统计信息不含密钥", "SECRET-ABCDEF" not in stats_txt)
    log_path = os.path.join(_TMP, "logs")
    leaked = False
    if os.path.isdir(log_path):
        for name in os.listdir(log_path):
            if "SECRET-ABCDEF" in io.open(os.path.join(log_path, name),
                                          encoding="utf-8", errors="replace").read():
                leaked = True
    check("日志文件不含密钥", not leaked)
    http.configure_ncbi(None)

    print(f"\n通过 {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print(f"临时目录：{_TMP}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
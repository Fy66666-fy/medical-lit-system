"""可插拔翻译层：腾讯云机器翻译 TMT（主力）+ MyMemory（免费兜底）。

背景：MyMemory 匿名接口按 IP 限免费额度（约 5000 字符/天），对外发行不够用。
腾讯云 TMT 通用文本翻译每月有 500 万字符免费额度（个人认证即可开通），
本模块实现 TC3-HMAC-SHA256 签名调用，无需额外依赖（仅 requests）。

凭据来源优先级（app.py 启动时通过 configure() 注入）：
  1. 侧边栏用户输入（session_state）
  2. Streamlit Cloud 的 st.secrets / 本地环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
未配置凭据或腾讯调用失败时，自动回退 MyMemory 免费接口，行为与旧版一致。
"""
import datetime
import hashlib
import hmac
import json
import os

import requests  # 仅用于异常类型；实际请求统一走 core.http（超时/重试/限流/埋点）

from core import http

_TMT_URL = "https://tmt.tencentcloudapi.com"
_TMT_HOST = "tmt.tencentcloudapi.com"
_TMT_SERVICE = "tmt"
_TMT_VERSION = "2018-03-21"

# 运行时凭据（configure() 注入；空 = 未配置）
_CRED = {"secret_id": "", "secret_key": "", "region": "ap-guangzhou"}


def configure(secret_id: str, secret_key: str, region: str = "ap-guangzhou") -> None:
    """注入腾讯云凭据（app.py 每次脚本运行时调用）。传空串视为清除。"""
    _CRED["secret_id"] = (secret_id or "").strip()
    _CRED["secret_key"] = (secret_key or "").strip()
    if region:
        _CRED["region"] = region


def _env_creds() -> tuple[str, str]:
    return (
        os.environ.get("TENCENT_SECRET_ID", "").strip(),
        os.environ.get("TENCENT_SECRET_KEY", "").strip(),
    )


def has_tencent() -> bool:
    sid, skey = _CRED["secret_id"], _CRED["secret_key"]
    if not (sid and skey):
        sid, skey = _env_creds()
    return bool(sid and skey)


def _active_creds() -> tuple[str, str]:
    sid, skey = _CRED["secret_id"], _CRED["secret_key"]
    if not (sid and skey):
        sid, skey = _env_creds()
    return sid, skey


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def tencent_translate(text: str, source: str = "en", target: str = "zh") -> str:
    """调用腾讯云 TMT TextTranslate。失败抛异常，由上层决定是否回退。"""
    sid, skey = _active_creds()
    if not (sid and skey):
        raise RuntimeError("腾讯云翻译未配置凭据")

    payload = json.dumps(
        {"SourceText": text, "Source": source, "Target": target, "ProjectId": 0}
    )
    timestamp = int(datetime.datetime.now().timestamp())
    date = datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc).strftime("%Y-%m-%d")

    # ---- TC3-HMAC-SHA256 签名（腾讯云官方算法）----
    canonical_request = "\n".join([
        "POST",
        "/",
        "",
        f"content-type:application/json; charset=utf-8\nhost:{_TMT_HOST}\n",
        "content-type;host",
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    ])
    string_to_sign = "\n".join([
        "TC3-HMAC-SHA256",
        str(timestamp),
        f"{date}/{_TMT_SERVICE}/tc3_request",
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])
    k_date = _hmac_sha256(("TC3" + skey).encode("utf-8"), date)
    k_service = _hmac_sha256(k_date, _TMT_SERVICE)
    k_signing = _hmac_sha256(k_service, "tc3_request")
    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Host": _TMT_HOST,
        "X-TC-Action": "TextTranslate",
        "X-TC-Version": _TMT_VERSION,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Region": _CRED["region"],
        "Authorization": (
            f"TC3-HMAC-SHA256 Credential={sid}/{date}/{_TMT_SERVICE}/tc3_request, "
            f"SignedHeaders=content-type;host, Signature={signature}"
        ),
    }
    # 腾讯云为计费接口，只保留 1 次网络 / 5xx 重试；超时与退避由 core.http 统一处理
    r = http.post(
        _TMT_URL, headers=headers, data=payload.encode("utf-8"), timeout=30, retries=1
    )
    r.raise_for_status()
    data = r.json()
    resp = data.get("Response") or {}
    err = resp.get("Error")
    if err:
        raise RuntimeError(f"TMT {err.get('Code')}: {err.get('Message')}")
    out = (resp.get("TargetText") or "").strip()
    if not out:
        raise RuntimeError("TMT 返回空译文")
    return out


def _langpair_split(langpair: str) -> tuple[str, str]:
    """'en|zh-CN' → ('en', 'zh')；腾讯目标语言用 'zh'，MyMemory 用 'zh-CN'"""
    src, _, tgt = (langpair or "en|zh-CN").partition("|")
    tgt_tc = {"zh-CN": "zh", "zh-TW": "zh-TW", "zh": "zh"}.get(tgt, tgt)
    return src or "en", tgt_tc


# ---------------- MyMemory 免费接口（兜底） ----------------

def _mymemory_request(q: str, langpair: str, timeout: int = 30) -> str:
    """单次 MyMemory 请求，返回 responseData.translatedText；失败抛异常。"""
    r = http.get(
        "https://api.mymemory.translated.net/get",
        params={"q": q, "langpair": langpair},
        timeout=timeout, retries=2,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("responseStatus") != 200:
        raise RuntimeError("MyMemory 返回异常")
    out = (data.get("responseData") or {}).get("translatedText") or ""
    if not out:
        raise RuntimeError("MyMemory 返回空译文")
    return out


def translate_segment(text: str, langpair: str = "en|zh-CN") -> str:
    """句段级翻译主入口：腾讯优先，失败静默回退 MyMemory；两者都失败抛异常。"""
    if has_tencent():
        src, tgt = _langpair_split(langpair)
        try:
            return tencent_translate(text, src, tgt)
        except Exception:
            pass  # 回退 MyMemory
    return _mymemory_request(text, langpair)


def translate_keyword(term: str, langpair: str = "en|zh-CN") -> tuple[str, str]:
    """单词级关键词翻译。返回 (译文, 提供方)；提供方用于上层选择不同校验策略。"""
    if has_tencent():
        src, tgt = _langpair_split(langpair)
        try:
            return tencent_translate(term, src, tgt), "tencent"
        except Exception:
            pass
    try:
        return _mymemory_request(term, langpair, timeout=15), "mymemory"
    except Exception:
        return term, "none"

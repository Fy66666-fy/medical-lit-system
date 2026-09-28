"""翻译层自测：腾讯 TMT 签名结构 / 回退链 / MyMemory 兜底 / 关键词校验"""
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, ".")

from core import translate, summarizer


class TestLangpair(unittest.TestCase):
    def test_split(self):
        self.assertEqual(translate._langpair_split("en|zh-CN"), ("en", "zh"))
        self.assertEqual(translate._langpair_split("en|zh-TW"), ("en", "zh-TW"))
        self.assertEqual(translate._langpair_split(""), ("en", "zh"))


class TestTencentSign(unittest.TestCase):
    """验证 TC3 签名请求结构与 payload"""

    def test_request_structure(self):
        translate.configure("AKIDtest", "secrettest")
        fake = mock.Mock()
        fake.json.return_value = {"Response": {"TargetText": "乳腺癌", "RequestId": "x"}}
        fake.raise_for_status = lambda: None
        with mock.patch.object(translate.requests, "post", return_value=fake) as mp:
            out = translate.tencent_translate("breast cancer", "en", "zh")
        self.assertEqual(out, "乳腺癌")
        args, kwargs = mp.call_args
        self.assertEqual(args[0], "https://tmt.tencentcloudapi.com")
        hdr = kwargs["headers"]
        self.assertTrue(hdr["Authorization"].startswith("TC3-HMAC-SHA256 Credential=AKIDtest/"))
        self.assertIn("SignedHeaders=content-type;host, Signature=", hdr["Authorization"])
        self.assertEqual(hdr["X-TC-Action"], "TextTranslate")
        self.assertEqual(hdr["X-TC-Version"], "2018-03-21")
        self.assertEqual(hdr["X-TC-Region"], "ap-guangzhou")
        payload = json.loads(kwargs["data"].decode("utf-8"))
        self.assertEqual(payload, {"SourceText": "breast cancer", "Source": "en",
                                   "Target": "zh", "ProjectId": 0})
        translate.configure("", "")  # 清理


class TestFallbackChain(unittest.TestCase):
    def setUp(self):
        translate.configure("", "")  # 无腾讯凭据 → 直接走 MyMemory

    def test_no_creds_uses_mymemory(self):
        self.assertFalse(translate.has_tencent())
        fake = mock.Mock()
        fake.json.return_value = {"responseStatus": 200,
                                  "responseData": {"translatedText": "肿瘤"}}
        fake.raise_for_status = lambda: None
        with mock.patch.object(translate.requests, "get", return_value=fake) as mp:
            out = translate.translate_segment("tumor", "en|zh-CN")
        self.assertEqual(out, "肿瘤")
        args, kwargs = mp.call_args
        self.assertIn("api.mymemory.translated.net", args[0])

    def test_tencent_fail_falls_back(self):
        translate.configure("AKIDtest", "secrettest")
        try:
            fake = mock.Mock()
            fake.json.return_value = {"responseStatus": 200,
                                      "responseData": {"translatedText": "细胞"}}
            fake.raise_for_status = lambda: None
            with mock.patch.object(translate, "tencent_translate",
                                   side_effect=RuntimeError("boom")), \
                 mock.patch.object(translate.requests, "get", return_value=fake) as mp:
                out = translate.translate_segment("cell", "en|zh-CN")
            self.assertEqual(out, "细胞")
            self.assertIn("api.mymemory.translated.net", mp.call_args[0][0])
        finally:
            translate.configure("", "")

    def test_both_fail_raises(self):
        with mock.patch.object(translate, "tencent_translate",
                               side_effect=RuntimeError("boom")), \
             mock.patch.object(translate.requests, "get",
                               side_effect=Exception("net down")):
            with self.assertRaises(Exception):
                translate.translate_segment("hello", "en|zh-CN")


class TestKeyword(unittest.TestCase):
    def setUp(self):
        translate.configure("", "")
        summarizer._KW_TRANS_CACHE.clear()

    def tearDown(self):
        translate.configure("", "")

    def test_glossary_first(self):
        out = summarizer.translate_keywords(["cell", "tumor"])
        self.assertEqual(out, ["细胞", "肿瘤"])

    def test_mymemory_junk_rejected(self):
        # MyMemory 返回词典义垃圾（如 "use" → 释义长串）时应回退英文
        fake = mock.Mock()
        fake.json.return_value = {"responseStatus": 200,
                                  "responseData": {"translatedText": "v.行使 ,用,用益权,运用"}}
        fake.raise_for_status = lambda: None
        with mock.patch.object(translate.requests, "get", return_value=fake):
            out = summarizer.translate_keywords(["useless_term_xyz"])
        self.assertEqual(out, ["useless_term_xyz"])

    def test_tencent_keyword_accepted(self):
        summarizer._KW_TRANS_CACHE.clear()
        translate.configure("AKIDtest", "secrettest")
        try:
            with mock.patch.object(translate, "tencent_translate",
                                   return_value="血管生成"), \
                 mock.patch.object(summarizer.time, "sleep"):
                out = summarizer.translate_keywords(["angiogenesis"])
            self.assertEqual(out, ["血管生成"])
        finally:
            translate.configure("", "")
            summarizer._KW_TRANS_CACHE.clear()


class TestLive(unittest.TestCase):
    """真实联网（MyMemory 免费接口，不消耗额度）"""

    def test_live_mymemory(self):
        try:
            out = translate._mymemory_request("breast cancer", "en|zh-CN")
        except Exception as e:
            self.skipTest(f"网络不可用：{e}")
        self.assertTrue(out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

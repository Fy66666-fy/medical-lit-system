# -*- coding: utf-8 -*-
"""3.11 兼容性扫描：f-string 表达式段内不得跨行（PEP 701 才放开）。
自校验：git HEAD 旧版 core/review.py 已知 2427 行违规，必须被抓到。
"""
import ast
import glob
import io
import sys
import tokenize

FILES = sorted(set(glob.glob("*.py") + glob.glob("core/*.py")))


def scan(src, label):
    bad = 0
    stack = []  # [start_line, triple, depth, prev_end_line]
    try:
        toks = tokenize.generate_tokens(io.StringIO(src).readline)
        for t in toks:
            tn, ts, st, en = t.type, t.string, t.start, t.end
            name = tokenize.tok_name[tn]
            if name == "FSTRING_START":
                q = ts.lstrip("rbuRBUFf")
                stack.append([st[0], q in ("'''", '"""'), 0, st[0]])
                continue
            if not stack:
                continue
            g = stack[-1]
            if name == "FSTRING_END":
                if not g[1] and en[0] != g[0]:
                    bad += 1
                    print(f"[{label}:{g[0]}] 单引号 f-string 跨行至 {en[0]}（3.11 禁止）")
                if g[2] > 0:
                    bad += 1
                    print(f"[{label}:{g[0]}] f-string 结束时表达式段未闭合")
                stack.pop()
                continue
            if name == "OP":
                if ts == "{":
                    g[2] += 1
                elif ts == "}":
                    g[2] = max(0, g[2] - 1)
            in_expr = g[2] > 0
            literal_mid = name == "FSTRING_MIDDLE" and not in_expr
            if st[0] > g[3] and (in_expr or (not g[1] and not literal_mid)):
                why = "表达式段跨行" if in_expr else "单引号 f-string 跨行"
                bad += 1
                print(f"[{label}:{g[0]}] {why}：{name} {ts[:60]!r} 落在第 {st[0]} 行")
            g[3] = max(g[3], en[0])
    except Exception as e:
        print(f"[{label}] tokenize 失败: {e}")
        return 1
    return bad


def main():
    # 自校验：内置的已知违规样本必须被抓到（不依赖 git 历史）
    bad_src = (
        "x = 1\n"
        "L.append(f\"**结论**：{todo('一句话，'\n"
        "                         '第二行')}\")\n"
    )
    n0 = scan(bad_src, "SELFTEST:builtin")
    if n0 == 0:
        print("!! 自校验失败：扫描器抓不到已知违规，结果不可信")
        return 2
    print(f"自校验通过（抓到 {n0} 处）\n----")
    total = 0
    for p in FILES:
        total += scan(io.open(p, encoding="utf-8").read(), p)
    print("----\n违规总数:", total)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())

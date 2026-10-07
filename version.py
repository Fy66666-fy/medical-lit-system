"""版本单一来源（v2.5.0）。

此前版本号散落在 app.py、使用说明.md、ROADMAP.md、打包脚本等多处，
每次发版靠手工同步，漏改就会出现"页面显示 v2.3.0、实际代码是 v2.4.0"的错位。
现在所有地方统一从这里读取，发版只需 release.py 改这一个数字。
"""
from __future__ import annotations

# 语义化版本（major.minor.patch），带 v 前缀是页面展示用的既有格式
APP_VERSION = "v2.5.0"

# 内部比较用的数字元组，CI / 发布脚本判断是否需要 bump 时使用
VERSION_TUPLE = (2, 5, 0)


def bump(part: str = "patch") -> str:
    """返回递增后的版本号字符串（不写文件，供 release.py 决定并落盘）。"""
    major, minor, patch = VERSION_TUPLE
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"v{major}.{minor}.{patch}"


if __name__ == "__main__":
    print(APP_VERSION)

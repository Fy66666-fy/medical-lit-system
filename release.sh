#!/usr/bin/env bash
# 医学文献智能摘要系统 · 一键发布（Linux / macOS / WSL）
#
# 等价于 Windows 的「一键发布.bat」：跑测试 → 改版本 → 同步部署目录
#   → 提交打标签 → 推送（内置直连 IP 轮换兜底）。
#
# 用法：
#     ./release.sh                       # 默认 patch 递增
#     ./release.sh minor "新增 XX 功能"
#     ./release.sh --set v3.1.0 "..."     # 直接指定版本（支持 --set/--no-push 等原参数）
#     ./release.sh patch --no-push
#
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PYTHON=".venv/Scripts/python.exe"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  PYTHON="python"
fi

# 无参数 → 默认 patch；首参是 --xxx → 直接透传原参数
if [ "$#" -eq 0 ]; then
  set -- --bump patch
elif [ "${1#--}" = "$1" ]; then
  PART="$1"; shift
  if [ "$#" -gt 0 ]; then MSG="$1"; shift; else MSG=""; fi
  set -- --bump "$PART" --message "$MSG" "$@"
fi

echo "使用解释器：$PYTHON"
exec "$PYTHON" release.py "$@"

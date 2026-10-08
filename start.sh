#!/usr/bin/env bash
# 医学文献智能摘要系统 · 本地启动（Linux / macOS / WSL）
#
# 等价于 Windows 的「一键启动.bat」：找解释器 → 起 Streamlit → 等端口真正就绪 → 开浏览器。
# 端口被占用时的处理逻辑全在 launch.py 里（是自己就复用、是别人就自动换端口）。
#
# 用法：
#     ./start.sh                 # 默认 8501，就绪后自动开浏览器
#     ./start.sh --port 8600
#     ./start.sh --no-browser    # 不自动开浏览器（WSL 里 xdg-open 不通时用这个）
#     MEDLIT_PORT=8600 ./start.sh
#
set -euo pipefail

cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
  PYTHON=".venv/Scripts/python.exe"        # 从 Windows 侧建的 venv 直接复用
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  PYTHON="python"
fi

if ! "$PYTHON" -c "import streamlit" >/dev/null 2>&1; then
  echo "[错误] 当前解释器（$PYTHON）里没有 streamlit。"
  echo "  先执行：  ./setup.sh"
  exit 9
fi

# 启动器要等端口就绪再开浏览器，避免「浏览器转圈以为网慢」
exec "$PYTHON" launch.py "$@"

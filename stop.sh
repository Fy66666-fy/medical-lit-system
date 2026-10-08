#!/usr/bin/env bash
# 医学文献智能摘要系统 · 停止服务（Linux / macOS / WSL）
#
# 等价于 Windows 的「一键停止.bat」：按端口找到本项目进程并结束。
# 识别逻辑（宁可放过不误杀）在 stop.py 里：先比 /proc/<pid>/cwd，再看命令行。
#
# 用法：
#     ./stop.sh                  # 停 8501 上本项目的实例
#     ./stop.sh --port 8600
#     ./stop.sh --all            # 扫 8501~8520 全停
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

if [ "$#" -eq 0 ]; then
  exec "$PYTHON" stop.py --port "${MEDLIT_PORT:-8501}" --all
fi
exec "$PYTHON" stop.py "$@"

#!/usr/bin/env bash
# 医学文献智能摘要系统 · 环境准备（Linux / macOS / WSL）
#
# 做三件事：建项目内 venv → 升级 pip → 装 requirements.txt。
# 幂等：重复执行只会更新依赖，不会重建已有 venv。
#
# 用法：
#     ./setup.sh
#
set -euo pipefail

cd "$(dirname "$0")"

# ---- 1. 检查 python3 ----
if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "[错误] 没找到 Python 3。"
  echo "  Ubuntu / WSL：  sudo apt update && sudo apt install -y python3 python3-venv python3-pip"
  exit 9
fi
echo "[1/3] 解释器：$($PY --version 2>&1)  ($(command -v $PY))"

if ! "$PY" -c "import venv" >/dev/null 2>&1; then
  echo "[错误] 缺少 venv 模块。Ubuntu / WSL：sudo apt install -y python3-venv"
  exit 9
fi

# ---- 2. 建 venv ----
if [ -x ".venv/bin/python" ]; then
  echo "[2/3] 复用已有 .venv"
else
  echo "[2/3] 创建 .venv"
  "$PY" -m venv .venv
fi

# ---- 3. 装依赖 ----
echo "[3/3] 安装依赖（requirements.txt）"
./.venv/bin/python -m pip install --upgrade pip --quiet
./.venv/bin/python -m pip install -r requirements.txt

echo
echo "完成。启动服务：  ./start.sh"
echo
echo "可选（只有要用到才装）："
echo "  改图表解析的浏览器兜底  →  sudo apt install -y chromium-browser"
echo "  重新生成落地页截图      →  sudo apt install -y chromium-browser（_shot.py 会自动找）"
echo "  打 Linux 桌面版          →  sudo apt install -y libwebkit2gtk-4.1-dev && ./.venv/bin/pip install pyinstaller pywebview"

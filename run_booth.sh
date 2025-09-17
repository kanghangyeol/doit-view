#!/usr/bin/env bash
set -euo pipefail

# --- Supabase 환경변수 (네 프로젝트 값으로 교체) ---
export SUPABASE_URL="https://qzcfjssimpxniwibxxit.supabase.co"
export SUPABASE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF6Y2Zqc3NpbXB4bml3aWJ4eGl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTUzMzAzOTUsImV4cCI6MjA3MDkwNjM5NX0.J4Xd_pq0pfj_hNB_VGt9WoliXRA1hJ0oBnhf_tjbDPw"
export SUPABASE_SERVICE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InF6Y2Zqc3NpbXB4bml3aWJ4eGl0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTUzMzAzOTUsImV4cCI6MjA3MDkwNjM5NX0.J4Xd_pq0pfj_hNB_VGt9WoliXRA1hJ0oBnhf_tjbDPw"

# 필수 변수 확인
for v in SUPABASE_URL SUPABASE_KEY SUPABASE_SERVICE_KEY; do
  if [ -z "${!v:-}" ]; then
    echo "[ERR] $v 가 비어있습니다." >&2
    exit 1
  fi
done

# --- 깨끗한 Qt 플러그인 환경으로 시작 ---
unset QT_QPA_PLATFORM_PLUGIN_PATH
unset QT_PLUGIN_PATH

PY="$HOME/Desktop/Do_IT/.venv312/bin/python"
APP="$HOME/Desktop/Do_IT/ui_booth.py"

# PySide6가 설치된 venv 안의 Qt 플러그인 경로 주입
"$PY" - <<'PY'
import os, importlib.util
from pathlib import Path
spec = importlib.util.find_spec("PySide6")
if spec and spec.submodule_search_locations:
    base = Path(list(spec.submodule_search_locations)[0])
    plugs = base / "Qt" / "plugins"
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugs / "platforms")
    os.environ["QT_PLUGIN_PATH"] = str(plugs)
print("[OK] QT paths set")
PY

# 앱 실행 (실패 시 디버그 모드로 재시도)
if ! exec "$PY" "$APP"; then
  echo "[!] Launch failed. Retrying with QT_DEBUG_PLUGINS=1..." >&2
  export QT_DEBUG_PLUGINS=1
  exec "$PY" "$APP"
fi
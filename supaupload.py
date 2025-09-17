# supaupload.py
import os
import mimetypes
import requests
from pathlib import Path
from urllib.parse import quote

# ─────────────────────────────────────────────────────────
# 환경변수 로드 + 보정
# ─────────────────────────────────────────────────────────
def _get_env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"환경변수 {name} 가 설정되지 않았습니다.")
    return val

def _normalize_base_url(url: str) -> str:
    # 앞뒤 공백 제거, http 스킴 없으면 https:// 붙임, 끝의 / 제거
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")

SUPABASE_URL   = _normalize_base_url(_get_env("SUPABASE_URL"))   # 예: https://qzcfjssimpxniwibxxit.supabase.co
SERVICE_KEY    = _get_env("SUPABASE_SERVICE_KEY")                # 서비스 롤 키
DEFAULT_BUCKET = os.environ.get("SUPABASE_BUCKET", "sessions")   # 기본 버킷 이름

# ─────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────
def _as_str(p) -> str:
    return str(p) if isinstance(p, Path) else p

def _guess_content_type(local_path, given: str | None) -> str:
    if given:
        return given
    path_str = _as_str(local_path)
    lower = path_str.lower()
    # 명시 매핑(믿을 수 있게)
    if lower.endswith(".html"):
        return "text/html; charset=utf-8"
    if lower.endswith(".json"):
        return "application/json; charset=utf-8"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".svg"):
        return "image/svg+xml"
    # 폴백
    return mimetypes.guess_type(path_str)[0] or "application/octet-stream"

def _encode_object_path(object_path: str) -> str:
    # 선행 슬래시 제거 + URL 인코딩(경로구분자 / 는 유지)
    return quote(object_path.lstrip("/"), safe="/")

def _upload_url(bucket: str, object_path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/{bucket}/{_encode_object_path(object_path)}"

def _public_url(bucket: str, object_path: str) -> str:
    return f"{SUPABASE_URL}/storage/v1/object/public/{bucket}/{_encode_object_path(object_path)}"

# ─────────────────────────────────────────────────────────
# 업로드
# ─────────────────────────────────────────────────────────
def supa_upload(
    local_path,
    object_path: str,
    content_type: str | None = None,
    is_public: bool = True,
    bucket: str | None = None,
) -> str:
    """
    Supabase Storage 업로드
      - local_path: 로컬 파일 경로(str | Path)
      - object_path: 버킷 내 경로(예: "a1b2c3/meta.json")
      - content_type: 지정 없으면 자동 추론
      - is_public: 공개 URL 반환 여부(True 권장, 버킷이 Public 정책이어야 브라우저 접근 가능)
      - bucket: 지정 없으면 DEFAULT_BUCKET 사용
    반환값: 공개 URL(기본) 또는 업로드 엔드포인트(URL)
    """
    lp_str = _as_str(local_path)
    ct = _guess_content_type(lp_str, content_type)
    b  = bucket or DEFAULT_BUCKET

    with open(lp_str, "rb") as f:
        data = f.read()

    url = _upload_url(b, object_path)
    headers = {
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": ct,
        "x-upsert": "true",  # 같은 경로 덮어쓰기
    }

    resp = requests.post(url, headers=headers, data=data, timeout=30)
    if resp.status_code not in (200, 201):
        raise RuntimeError(f"Supabase upload failed ({resp.status_code}): {resp.text.strip()}")

    return _public_url(b, object_path) if is_public else url

# ─────────────────────────────────────────────────────────
# 삭제(옵션)
# ─────────────────────────────────────────────────────────
def supa_remove(object_path: str, bucket: str | None = None) -> bool:
    b = bucket or DEFAULT_BUCKET
    url = f"{SUPABASE_URL}/storage/v1/object/{b}/{_encode_object_path(object_path)}"
    headers = {
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    resp = requests.delete(url, headers=headers, timeout=15)
    return resp.status_code in (200, 204)
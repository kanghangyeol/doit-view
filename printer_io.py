# printer_io.py (USB 전용 · 최대 화질 전처리)
from __future__ import annotations
from typing import Tuple, Optional, List
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import glob

# ──────────────────────────────────────────────────────────────
# 선택 의존성: pyserial (USB 출력용)
#   pip install pyserial
# ──────────────────────────────────────────────────────────────
HAVE_PYSERIAL = False
Serial = None
try:
    from serial import Serial as _Serial
    Serial = _Serial
    HAVE_PYSERIAL = True
except Exception:
    pass


# =============================================================
# 유틸
# =============================================================
def _gamma_lut(gamma: float) -> list[int]:
    """0..255 감마 LUT"""
    gamma = max(0.1, float(gamma))
    return [min(255, max(0, int(((i / 255.0) ** (1.0 / gamma)) * 255 + 0.5))) for i in range(256)]


def _ensure_multiple_of_8(w: int) -> int:
    """ESC/POS 래스터는 가로 픽셀이 8의 배수여야 안정적."""
    return (w // 8) * 8


# =============================================================
# 전처리 (최고 화질 권장 프로파일)
# =============================================================
def _prep_image_1bpp(
    im: Image.Image,
    target_width: int,
    *,
    profile: str = "photo",            # "photo" | "text" | "qr"
    # 공통 튜닝 값 (photo 기준; 필요시 조절)
    autocontrast_cutoff: int = 2,      # 0~3% 권장 (끝단 확장)
    gamma: float = 0.90,               # <1.0 이면 중간톤 진해져 질감↑
    sharpness: float = 1.35,           # 1.1~1.5 정도
    unsharp_radius: float = 1.0,       # 언샤프 마스크 반경
    unsharp_percent: int = 120,        # 80~160
    unsharp_threshold: int = 3,        # 노이즈 억제
    contrast: float = 1.08,            # 약간만
    brightness: float = 1.00,          # 보통 1.0
    ordered_dither: bool = False,      # True면 Bayer(Ordered) 디더; 사진은 FS 권장
    threshold: int = 160,              # profile="text"/"qr" 에서 사용
) -> Image.Image:
    """
    흐름:
      1) Grayscale
      2) LANCZOS 리사이즈(가로 8배수 보정)
      3) AutoContrast / Gamma / Contrast / Brightness
      4) UnsharpMask + Sharpness
      5) 1bpp 변환 (photo: 디더, text/qr: 임계값)
    """
    g = im.convert("L")

    # 2) 목표 폭(점수폭)에 정확히 맞춤
    if target_width:
        tw = _ensure_multiple_of_8(int(target_width))
        if g.width != tw:
            ratio = tw / g.width
            g = g.resize((tw, max(1, int(g.height * ratio))), Image.LANCZOS)

    # 3) 톤 보정
    if autocontrast_cutoff > 0:
        g = ImageOps.autocontrast(g, cutoff=int(autocontrast_cutoff))
    if abs(gamma - 1.0) > 1e-3:
        g = g.point(_gamma_lut(gamma))
    if abs(contrast - 1.0) > 1e-3:
        g = ImageEnhance.Contrast(g).enhance(float(contrast))
    if abs(brightness - 1.0) > 1e-3:
        g = ImageEnhance.Brightness(g).enhance(float(brightness))

    # 4) 선명도 보정 (언샤프 → 샤프니스)
    if unsharp_percent > 0 and unsharp_radius > 0:
        g = g.filter(ImageFilter.UnsharpMask(
            radius=float(unsharp_radius),
            percent=int(unsharp_percent),
            threshold=int(unsharp_threshold),
        ))
    if abs(sharpness - 1.0) > 1e-3:
        g = ImageEnhance.Sharpness(g).enhance(float(sharpness))

    # 5) 1비트 변환
    if profile == "photo":
        # 사진은 FS 디더가 질감/톤 그라데이션을 가장 부드럽게 만듦
        if ordered_dither:
            # Ordered(바이어) 디더는 질감이 일정한 패턴으로, 사진에선 취향 차이
            return g.convert("1", dither=Image.Dither.ORDERED)
        return g.convert("1", dither=Image.Dither.FLOYDSTEINBERG)

    # 텍스트/QR은 가장 또렷함이 중요 → 임계값
    t = max(0, min(255, int(threshold)))
    return g.point(lambda x: 0 if x < t else 255, mode="1")


def _pil_to_raster_bytes_bw(
    img: Image.Image,
    paper_width_px: int,
    *,
    # 전처리 프로파일
    profile: str = "photo",            # "photo" | "text" | "qr"
    # 세부 튜닝 (photo 기본값으로 최대 화질)
    autocontrast_cutoff: int = 2,
    gamma: float = 0.90,
    sharpness: float = 1.35,
    unsharp_radius: float = 1.0,
    unsharp_percent: int = 120,
    unsharp_threshold: int = 3,
    contrast: float = 1.08,
    brightness: float = 1.00,
    ordered_dither: bool = False,
    threshold: int = 160,
) -> bytes:
    """
    이미지를 용지폭에 맞춰 1bpp로 만든 뒤 ESC/POS 'GS v 0' 래스터 포맷으로 변환.
    (m=0: 1x 밀도. 스케일을 키우는 m=1~3은 해상도↑가 아니라 확대이므로 품질 개선 X)
    """
    bw = _prep_image_1bpp(
        img,
        paper_width_px,
        profile=profile,
        autocontrast_cutoff=autocontrast_cutoff,
        gamma=gamma,
        sharpness=sharpness,
        unsharp_radius=unsharp_radius,
        unsharp_percent=unsharp_percent,
        unsharp_threshold=unsharp_threshold,
        contrast=contrast,
        brightness=brightness,
        ordered_dither=ordered_dither,
        threshold=threshold,
    )

    width, height = bw.size
    row_bytes = (width + 7) // 8
    data = bytearray(row_bytes * height)

    px = bw.load()
    idx = 0
    for y in range(height):
        byte = 0
        bit = 0
        for x in range(width):
            # '1' 모드: 0=검정, 255=흰색
            is_black = 1 if px[x, y] == 0 else 0
            byte = (byte << 1) | is_black
            bit += 1
            if bit == 8:
                data[idx] = byte
                idx += 1
                byte = 0
                bit = 0
        if bit != 0:
            byte <<= (8 - bit)
            data[idx] = byte
            idx += 1

    # ESC/POS Raster Bit Image 헤더 (m=0)
    xL = row_bytes & 0xFF
    xH = (row_bytes >> 8) & 0xFF
    yL = height & 0xFF
    yH = (height >> 8) & 0xFF
    header = bytes([0x1D, 0x76, 0x30, 0x00, xL, xH, yL, yH])
    return header + bytes(data)


# =============================================================
# USB 출력
# =============================================================
def list_usb_candidate_ports() -> List[str]:
    """macOS에서 흔한 CDC/시리얼 장치 경로 후보 나열."""
    return sorted(glob.glob("/dev/tty.usbmodem*") + glob.glob("/dev/tty.usbserial*"))


def _serial_write_all(ser, payload: bytes, chunk: int = 2048) -> None:
    """큰 이미지를 안정적으로 전송하기 위해 청크 분할."""
    for i in range(0, len(payload), chunk):
        ser.write(payload[i:i + chunk])


def _try_set_density_common(ser) -> None:
    """
    몇몇 EPSON-호환기기에서 먹는 인쇄 품질(밀도/속도) 힌트 명령들.
    기종마다 무시될 수 있음(안전).
    """
    try:
        # ESC 7: 일반적인 프린트 속도/밀도 관련 (기종에 따라 무시)
        # ser.write(b"\x1B\x37\x07\xFF")  # 예시: 일부 프린터에서 진하게
        # GS ( E: 인쇄 모드 파라미터 (EPSON 확장) - 모델에 따라 무시/오동작 가능 → 보수적으로 주석
        # ser.write(b"\x1D\x28\x45\x02\x00\x00\x00")  # 샘플
        pass
    except Exception:
        pass


def print_image_usb(
    image_path: str,
    device: Optional[str] = None,      # 예) '/dev/tty.usbmodem1101'; None이면 자동탐색
    baudrate: int = 115200,
    paper_width_px: int = 576,         # 80mm=576, 58mm=384
    do_cut: bool = True,
    feed_after: int = 1,
    *,
    # 품질 프로파일/튜닝 (photo가 최대 화질 추천)
    profile: str = "photo",            # "photo" | "text" | "qr"
    autocontrast_cutoff: int = 2,
    gamma: float = 0.90,
    sharpness: float = 1.35,
    unsharp_radius: float = 1.0,
    unsharp_percent: int = 120,
    unsharp_threshold: int = 3,
    contrast: float = 1.08,
    brightness: float = 1.00,
    ordered_dither: bool = False,
    threshold: int = 160,
) -> Tuple[bool, str]:
    """
    USB(시리얼) ESC/POS 프린터로 이미지 출력 (pyserial 직접 전송).
    드라이버 없이도 CDC-ACM 장치로 잡히면 동작 가능.
    """
    if not HAVE_PYSERIAL or Serial is None:
        return False, "pyserial이 설치되지 않았습니다. (pip install pyserial)"

    try:
        img = Image.open(image_path)
    except Exception as e:
        return False, f"이미지 열기 실패: {e}"

    try:
        data = _pil_to_raster_bytes_bw(
            img,
            paper_width_px,
            profile=profile,
            autocontrast_cutoff=autocontrast_cutoff,
            gamma=gamma,
            sharpness=sharpness,
            unsharp_radius=unsharp_radius,
            unsharp_percent=unsharp_percent,
            unsharp_threshold=unsharp_threshold,
            contrast=contrast,
            brightness=brightness,
            ordered_dither=ordered_dither,
            threshold=threshold,
        )
    except Exception as e:
        return False, f"이미지 변환 실패: {e}"

    # 장치 자동 탐색
    dev = device
    if not dev:
        cands = list_usb_candidate_ports()
        if not cands:
            return False, "USB 프린터 포트를 찾지 못했습니다. (/dev/tty.usbmodem* / /dev/tty.usbserial*)"
        dev = cands[0]

    try:
        # 많은 ESC/POS USB-CDC 장치는 baudrate 무시(OK). 그래도 통상값으로 설정.
        with Serial(dev, baudrate=baudrate, timeout=2) as ser:
            # 초기화 & 정렬
            ser.write(b"\x1B\x40")      # ESC @ (init)
            ser.write(b"\x1B\x61\x01")  # ESC a 1 (center)
            ser.write(b"\x1B\x32")      # ESC 2 (기본 줄간격)
            _try_set_density_common(ser)

            # 이미지 래스터 전송(청크 분할)
            _serial_write_all(ser, data, chunk=2048)

            # 줄바꿈
            if feed_after > 0:
                ser.write(b"\n" * int(feed_after))

            # 컷(부분컷)
            if do_cut:
                ser.write(b"\x1D\x56\x42\x00")  # GS V B 0

            ser.flush()
        return True, f"USB 인쇄 완료 (port={dev})"
    except Exception as e:
        return False, f"USB 출력 실패: {e}"
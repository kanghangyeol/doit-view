# compose.py
from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont
import qrcode

# ----------------- 기본 유틸 -----------------
def fit_width_keep_aspect(im: Image.Image, width: int) -> Image.Image:
    if im.width == width:
        return im
    r = width / im.width
    return im.resize((width, int(im.height * r)), Image.LANCZOS)

def add_letterbox(im: Image.Image, width: int, pad_px: int) -> Image.Image:
    if pad_px <= 0:
        return im
    canvas = Image.new("RGB", (width, im.height + pad_px*2), (255, 255, 255))
    canvas.paste(im.convert("RGB"), (0, pad_px))
    return canvas

def load_logo(path: str, max_w: int, max_h: int) -> Image.Image | None:
    try:
        logo = Image.open(path).convert("RGBA")
    except Exception:
        return None
    w, h = logo.size
    scale = min(max_w / w, max_h / h, 1.0)
    logo = logo.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
    bg = Image.new("RGB", logo.size, (255, 255, 255))
    bg.paste(logo, (0, 0), mask=logo.split()[3])
    return bg

def make_qr_image(text: str, target_w: int) -> Image.Image:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_Q,
        box_size=9, border=2
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    tw = min(target_w, img.width)
    return fit_width_keep_aspect(img, tw)

def h_rule(width: int, height: int = 2) -> Image.Image:
    img = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([0, height//2, width, height//2], fill=(0, 0, 0))
    return img

def spacer(height: int, width: int) -> Image.Image:
    return Image.new("RGB", (width, height), (255, 255, 255))

# ----------------- 폰트/텍스트 블록 -----------------
def _load_font(path: str | None, size: int) -> ImageFont.ImageFont:
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()

def centered_text_block_safe(
    text: str,
    width: int,
    font: ImageFont.ImageFont,
    pad: int = 6,
    safety_px: int = 4,   # 오른쪽 끝 글자 잘림 방지용
) -> Image.Image:
    """
    - 가운데 정렬
    - 대략적 줄바꿈
    - 마지막 글자 잘림 방지 위해 폭에 safety_px 더해 작업 후, 원폭으로 크롭
    """
    import textwrap
    img_tmp = Image.new("RGB", (width, 10), (255, 255, 255))
    d_tmp = ImageDraw.Draw(img_tmp)

    # 평균 글자 폭 근사로 줄바꿈 폭 추정
    avg_char_w = max(6, getattr(font, "size", 22) // 2)
    max_chars = max(1, width // avg_char_w)

    lines = []
    for line in (text or "").splitlines():
        wrapped = textwrap.wrap(line, width=max_chars)
        lines.extend(wrapped if wrapped else [""])

    line_h = int(getattr(font, "size", 22) * 1.3)
    total_h = pad*2 + line_h*len(lines)

    work_w = width + safety_px
    img = Image.new("RGB", (work_w, total_h), (255, 255, 255))
    d = ImageDraw.Draw(img)

    y = pad
    for line in lines:
        # PIL의 textlength로 줄 전체 폭 계산
        tw = int(d.textlength(line, font=font))
        # 살짝의 여유를 고려
        tw_safe = tw + 2
        x = max(0, (width - tw_safe)//2)
        d.text((x, y), line, fill=(0, 0, 0), font=font)
        y += line_h

    # 작업 이미지는 safety_px만큼 더 넓으니 원래 width로 크롭해서 반환
    return img.crop((0, 0, width, total_h))

# ----------------- 합성 (이모지 없음 / 영수증 전용 문구) -----------------
def compose_receipt_two_photos(
    photos_pil: list[Image.Image],
    paper_width: int, margin: int, gap: int, photo_gap: int, letterbox_pad: int,
    logo_path: str, logo_max_h: int,
    qr_text: str, qr_max_w: int,
    receipt_text: str,                 # 영수증에만 들어갈 문구(링크 문구와 분리)
    font_path: str | None,
    date_text: str | None = None,
) -> Image.Image:

    # 폰트(본문/날짜)
    font_main = _load_font(font_path, 22)
    font_date = _load_font(font_path, 18)

    W, M, ww = paper_width, margin, paper_width - 2*margin
    blocks: list[Image.Image] = []

    # 로고
    logo = load_logo(logo_path, ww, logo_max_h)
    if logo:
        logo_wrap = Image.new("RGB", (ww, logo.height), (255, 255, 255))
        lx = (ww - logo.width) // 2
        logo_wrap.paste(logo, (lx, 0))
        blocks.append(logo_wrap)
        blocks.append(h_rule(ww, 2))
        blocks.append(spacer(15, ww))  # 필요시 더 줄여도 됨

    # 사진 1
    if photos_pil:
        ph1 = fit_width_keep_aspect(photos_pil[0].convert("RGB"), ww)
        ph1 = add_letterbox(ph1, ww, letterbox_pad)
        blocks.append(ph1)

    # 사진 간 간격
    if len(photos_pil) >= 2 and photo_gap > 0:
        blocks.append(Image.new("RGB", (ww, photo_gap), (255, 255, 255)))

    # 사진 2
    if len(photos_pil) >= 2:
        ph2 = fit_width_keep_aspect(photos_pil[1].convert("RGB"), ww)
        ph2 = add_letterbox(ph2, ww, letterbox_pad)
        blocks.append(ph2)

    # QR
    qr = make_qr_image(qr_text, qr_max_w)
    qr_can = Image.new("RGB", (ww, qr.height), (255, 255, 255))
    qr_can.paste(qr, ((ww - qr.width)//2, 0))
    blocks.append(qr_can)

    # 라인 + 영수증 문구(마지막 글자 안전)
    blocks.append(h_rule(ww, 2))
    blocks.append(centered_text_block_safe(receipt_text, ww, font_main, pad=6))

    # 날짜(있으면)
    if date_text:
        blocks.append(spacer(6, ww))
        blocks.append(centered_text_block_safe(date_text, ww, font_date, pad=2))

    # 상/하 여백(현 구성: 위 0, 아래 8)
    MT, MB = 0, 8
    total_h = MT + sum(b.height for b in blocks) + gap*(len(blocks)-1) + MB
    canvas = Image.new("RGB", (W, total_h), (255, 255, 255))

    # 합성
    y = MT
    for i, b in enumerate(blocks):
        canvas.paste(b, (M, y))
        y += b.height
        if i != len(blocks)-1:
            y += gap

    return canvas
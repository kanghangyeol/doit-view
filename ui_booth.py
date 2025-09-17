import os, sys
from pathlib import Path
from PySide6 import QtCore, QtWidgets, QtGui

import cv2, time, uuid, json
from PIL import Image

from compose import compose_receipt_two_photos
from supaupload import supa_upload
from printer_io import print_image_usb 

# ===== 고정값 / 기본값 =====
VIEW_HTML_PUBLIC = "https://kanghangyeol.github.io/doit-view/view.html"
LOGO_PUBLIC_URL  = "https://qzcfjssimpxniwibxxit.supabase.co/storage/v1/object/public/assets/Doit_logo.jpeg"

INSTAGRAM_URL       = "https://instagram.com/ajou_doit"
DEFAULT_SHORT_TEXT  = "JUST Do-IT!"
DEFAULT_FONT_PATH   = "/System/Library/Fonts/AppleSDGothicNeo.ttc"  # macOS

# 영수증(프린트 합성) 레이아웃 (80mm 고정)
PAPER_WIDTH         = 576           # 80mm
QR_MAX_W            = 160
DEFAULT_MARGIN      = 7
DEFAULT_GAP         = 4
DEFAULT_PHOTO_GAP   = 8
DEFAULT_LOGO_PATH   = "Doit_logo.jpeg"
DEFAULT_LETTERBOX   = 0
DEFAULT_LOGO_MAX_H  = 160

# --- 환경변수로 덮어쓰기(있는 경우에만) ---
_env_view = os.getenv("VIEW_URL")
if _env_view:
    VIEW_HTML_PUBLIC = _env_view

_env_logo = os.getenv("LOGO_PUBLIC_URL")
if _env_logo:
    LOGO_PUBLIC_URL = _env_logo

def open_capture(idx: int):
    """카메라 캡처 오픈 (macOS는 AVFoundation 고정)."""
    if sys.platform.startswith("darwin"):
        # AVFoundation로 강제 → OBSENSOR 우회
        return cv2.VideoCapture(idx, cv2.CAP_AVFOUNDATION)
    if sys.platform.startswith("win"):
        return cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    return cv2.VideoCapture(idx)

def _upload_with_type(local_path: Path, object_path: str, content_type: str | None):
    """
    supa_upload가 content_type 파라미터를 지원하지 않는 구버전일 수 있어
    TypeError 시 content_type 없이 재호출.
    """
    lp = str(local_path)
    try:
        return supa_upload(lp, object_path, content_type=content_type)
    except TypeError:
        return supa_upload(lp, object_path)

class BoothCam(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("두잇 영수증 사진관")
        self.resize(1200, 720)

        # 경로
        self.base_dir = Path(__file__).resolve().parent
        self.captures_dir = self.base_dir / "captures"
        self.captures_dir.mkdir(parents=True, exist_ok=True)

        # 상태
        self.cap = None
        self.timer = QtCore.QTimer(self); self.timer.timeout.connect(self._tick)
        self.mirror = True
        self.last_frame = None
        self.captured_images: list[tuple[Path, object]] = []
        self.max_shots = 2

        # 좌: 미리보기
        self.video = QtWidgets.QLabel("미리보기")
        self.video.setAlignment(QtCore.Qt.AlignCenter)
        self.video.setStyleSheet("background:#222; color:#aaa;")
        self.video.setMinimumSize(900, 650)

        # 우: 컨트롤
        self.device_combo = QtWidgets.QComboBox()
        self.snap_btn  = QtWidgets.QPushButton("촬영 (남은: 2)")
        self.print_btn = QtWidgets.QPushButton("프린트")
        self.reset_btn = QtWidgets.QPushButton("초기화")

        # 썸네일(2장): 버튼 폭에 맞춰 가로 확장
        self.thumb_labels = [QtWidgets.QLabel() for _ in range(2)]
        for lbl in self.thumb_labels:
            lbl.setFixedHeight(200)
            lbl.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            lbl.setStyleSheet("background:#555; border:2px solid #333;")
            lbl.setAlignment(QtCore.Qt.AlignCenter)

        # --- 짧은 문구 입력칸 (오른쪽 컬럼 폭에 맞춤, 2줄 고정) ---
        self.short_edit = QtWidgets.QTextEdit()
        self.short_edit.setAcceptRichText(False)
        self.short_edit.setWordWrapMode(QtGui.QTextOption.WordWrap)
        self.short_edit.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.short_edit.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.short_edit.setPlaceholderText("영수증 하단 안내 문구를 입력하세요.")
        self.short_edit.setPlainText(DEFAULT_SHORT_TEXT)
        self.short_edit.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)

        fm = self.short_edit.fontMetrics()
        line_h = fm.lineSpacing()
        self.short_edit.setFixedHeight(line_h * 2 + 14)  # 정확히 2줄

        self.short_edit.setStyleSheet("""
        QTextEdit {
          background: #ffffff;
          color: #111111;
          border: 1px solid #666666;
          border-radius: 6px;
          padding: 6px 8px;
        }
        """)

        # 로고 선택
        self.logo_edit  = QtWidgets.QLineEdit(DEFAULT_LOGO_PATH)
        self.logo_btn   = QtWidgets.QPushButton("로고 선택")

        # 옵션: 프린터(USB)
        self.chk_auto_reset = QtWidgets.QCheckBox("출력 후 자동 초기화")
        self.chk_auto_reset.setChecked(True)

        # ---- 오른쪽 UI 구성
        right = QtWidgets.QVBoxLayout()

        dev = QtWidgets.QHBoxLayout()
        dev.addWidget(QtWidgets.QLabel("장치:"))
        dev.addWidget(self.device_combo)
        right.addLayout(dev)

        right.addWidget(self.snap_btn)
        right.addWidget(self.print_btn)
        right.addWidget(self.reset_btn)
        right.addSpacing(6)

        right.addWidget(self.thumb_labels[0])
        right.addWidget(self.thumb_labels[1])
        right.addSpacing(6)

        # --- 내용 입력 (오른쪽 컬럼 풀폭, 버튼/썸네일과 동일 가로) ---
        # 라벨은 숨기고 입력칸만(요청사항)
        right.addWidget(self.short_edit)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        form.setLabelAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)

        row_logo = QtWidgets.QHBoxLayout()
        row_logo.addWidget(self.logo_edit)
        row_logo.addWidget(self.logo_btn)
        form.addRow("로고 파일(영수증용):", row_logo)

        right.addLayout(form)

        printer_row = QtWidgets.QHBoxLayout()

        self.chk_printer = QtWidgets.QCheckBox("프린터로 출력 (USB)")
        self.chk_printer.setChecked(True)
        printer_row.addWidget(self.chk_printer)
        
        printer_row.addStretch(1)
        
        printer_row.addWidget(QtWidgets.QLabel("인원수"))
        self.copies_combo = QtWidgets.QComboBox()
        self.copies_combo.addItems([str(i) for i in range(1, 11)])  # 1~10
        self.copies_combo.setCurrentText("1")
        self.copies_combo.setFixedWidth(70)
        printer_row.addWidget(self.copies_combo)
        
        right.addLayout(printer_row)

        # USB 출력 체크/옵션
        right.addWidget(self.chk_auto_reset)

        self.status = QtWidgets.QLabel("상태: 준비")
        self.status.setStyleSheet("color:#08c;")
        right.addSpacing(6)
        right.addWidget(self.status)

        # --- 루트 레이아웃 (왼쪽=미리보기, 오른쪽=컨트롤 고정폭) ---
        root = QtWidgets.QHBoxLayout(self)
        root.addWidget(self.video, 1)

        wrap = QtWidgets.QWidget()
        wrap.setLayout(right)
        wrap.setFixedWidth(330)
        root.addWidget(wrap, 0)

        # 이벤트
        self.device_combo.activated.connect(self._change_device)
        self.snap_btn.clicked.connect(self._capture_photo)
        self.print_btn.clicked.connect(self._print_both)
        self.reset_btn.clicked.connect(self._reset_all)
        self.logo_btn.clicked.connect(self._choose_logo)
        QtGui.QShortcut(QtGui.QKeySequence("Space"), self, activated=self._capture_photo)

        # 시작
        found = self._scan_0_1()
        if found:
            default = 1 if 1 in found else 0
            self.device_combo.setCurrentText(str(default))
            self._open_cap(default)
        else:
            self._set_status("사용 가능한 카메라 없음", err=True)

    # ---------- 카메라 ----------
    def _scan_0_1(self):
        self.device_combo.clear()
        found = []
        for i in (0, 1):
            cap = open_capture(i); ok, _ = cap.read(); cap.release()
            if ok: found.append(i)
        if found:
            for i in found: self.device_combo.addItem(str(i))
            self._set_status(f"검색: {found}")
        else:
            self.device_combo.addItem("0")
        return found

    def _change_device(self, _):
        try:
            idx = int(self.device_combo.currentText())
        except ValueError:
            idx = 0
        self._open_cap(idx)

    def _open_cap(self, idx: int):
        if self.cap:
            self.timer.stop(); self.cap.release(); self.cap = None
        self.cap = open_capture(idx)
        ok, _ = self.cap.read()
        if not ok:
            self.cap.release(); self.cap = None
            self._set_status(f"장치 {idx} 열기 실패", err=True); return
        self.timer.start(33)
        self._set_status(f"장치 {idx} 연결됨 (Space=촬영)")

    def _tick(self):
        if not self.cap: return
        ok, frame = self.cap.read()
        if not ok:
            self._set_status("프레임 읽기 실패", err=True); return
        if self.mirror:
            frame = cv2.flip(frame, 1)
        self.last_frame = frame
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QtGui.QImage(rgb.data, w, h, ch*w, QtGui.QImage.Format.Format_RGB888)
        pix = QtGui.QPixmap.fromImage(qimg).scaled(
            self.video.width(), self.video.height(),
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
        )
        self.video.setPixmap(pix)

    # ---------- 촬영/썸네일 ----------
    def _next_path(self, ts: str, idx: int) -> Path:
        return self.captures_dir / f"photo_{ts}_{idx+1:02d}.png"

    def _capture_photo(self):
        if self.last_frame is None:
            self._set_status("캡처할 프레임이 없어요.", err=True); return
        if len(self.captured_images) >= self.max_shots:
            self._set_status("촬영 기회 소진", err=True); return
        ts = time.strftime("%Y%m%d_%H%M")
        path = self._next_path(ts, len(self.captured_images))
        if cv2.imwrite(str(path), self.last_frame):
            self.captured_images.append((path, self.last_frame.copy()))
            self._update_thumbs()
            remain = self.max_shots - len(self.captured_images)
            self.snap_btn.setText(f"촬영 (남은: {remain})")
            self._set_status(f"저장됨: {path.name}")
        else:
            self._set_status("저장 실패", err=True)

    def _update_thumbs(self):
        for i, lbl in enumerate(self.thumb_labels):
            if i < len(self.captured_images):
                frame = self.captured_images[i][1]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = rgb.shape
                qimg = QtGui.QImage(rgb.data, w, h, ch*w, QtGui.QImage.Format.Format_RGB888)
                pix = QtGui.QPixmap.fromImage(qimg).scaled(
                    lbl.width(), lbl.height(),
                    QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation
                )
                lbl.setPixmap(pix)
                lbl.setStyleSheet("background:#555; border:3px solid #f0f000;")
            else:
                lbl.clear()
                lbl.setStyleSheet("background:#555; border:2px solid #333;")

    # ---------- 파일/다이얼로그 ----------
    def _choose_logo(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "로고 선택", os.getcwd(), "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self.logo_edit.setText(path)

    # ---------- 프린트(합성+저장+세션meta+옵션 출력) ----------
    def _print_both(self):
        if len(self.captured_images) < self.max_shots:
            self._set_status(f"사진을 {self.max_shots}장 모두 촬영하세요.", err=True)
            return

        # (고정) 용지/QR 폭
        paper_width = PAPER_WIDTH
        qr_max_w = QR_MAX_W

        QtGui.QGuiApplication.inputMethod().commit()
        QtWidgets.QApplication.processEvents()

        short_txt = (self.short_edit.toPlainText().strip() or DEFAULT_SHORT_TEXT)

        # 로고 경로 정규화 (상대경로 → 앱 폴더 기준)
        logo_path = (self.logo_edit.text().strip() or DEFAULT_LOGO_PATH)
        lp = Path(logo_path)
        if not lp.is_absolute():
            lp = self.base_dir / lp
        logo_path = str(lp)
        if not Path(logo_path).exists():
            self._set_status(f"로고 파일을 찾을 수 없습니다: {logo_path}", err=True)

        # 세션 ID + 임시 폴더
        session_id = uuid.uuid4().hex[:10]
        tmp_dir = self.captures_dir / f"tmp_{session_id}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # 사진 PNG 저장 + 업로드
        photos_pil, photos_urls = [], []
        for i, (_, frame_bgr) in enumerate(self.captured_images[:2], start=1):
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            pil_img = Image.fromarray(rgb); photos_pil.append(pil_img)
            fname = f"photo_{i:02d}.png"
            tmp_img = tmp_dir / fname
            pil_img.save(tmp_img)
            url = _upload_with_type(tmp_img, f"{session_id}/{fname}", content_type="image/png")
            photos_urls.append(url)

        # meta.json 작성 → 업로드 (view.html에서 사용)
        meta = {
            "photos": photos_urls,
            "instagram_url": INSTAGRAM_URL,
            "logo_url": LOGO_PUBLIC_URL,
        }
        meta_tmp = tmp_dir / "meta.json"
        with open(meta_tmp, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        try:
            meta_url = supa_upload(str(meta_tmp), f"{session_id}/meta.json", content_type="application/json")
            if not meta_url:
                raise RuntimeError("meta.json 업로드 결과가 비어 있음")
            print(f"[DEBUG] meta.json uploaded → {meta_url}")
        except Exception as e:
            self._set_status(f"meta.json 업로드 실패: {e}", err=True)
            return

        # 세션 페이지 URL
        view_base = VIEW_HTML_PUBLIC.rstrip("/")
        page_url = f"{view_base}?sid={session_id}"

        print("[DEBUG] session_id:", session_id)
        print("[DEBUG] page_url  :", page_url)
        self._set_status(f"페이지 URL: {page_url}")

        date_str = time.strftime("%Y.%m.%d")

        # 영수증 합성 PNG (컬러 유지)
        try:
            receipt = compose_receipt_two_photos(
                photos_pil=photos_pil,
                paper_width=paper_width,
                margin=DEFAULT_MARGIN,
                gap=DEFAULT_GAP,
                photo_gap=DEFAULT_PHOTO_GAP,
                letterbox_pad=DEFAULT_LETTERBOX,
                logo_path=logo_path,
                logo_max_h=DEFAULT_LOGO_MAX_H,
                qr_text=page_url,
                qr_max_w=qr_max_w,
                receipt_text=short_txt,
                font_path=DEFAULT_FONT_PATH,
                date_text=date_str,
            )
        except Exception as e:
            self._set_status(f"합성 실패: {e}", err=True)
            return

        ts = time.strftime("%Y%m%d_%H%M")
        out_path = self.captures_dir / f"RECEIPT_{ts}.png"
        try:
            receipt.save(out_path)
        except Exception as e:
            self._set_status(f"저장 실패: {e}", err=True)
            return

        self._set_status(f"저장됨: {out_path.resolve()}  |  페이지: {page_url}")
        print("SESSION PAGE:", page_url)

        # USB 프린터 출력
        success_cnt = 0 
        copies = 1 
        if self.chk_printer.isChecked():
            copies = int(self.copies_combo.currentText()) if hasattr(self, "copies_combo") else 1
            last_msg = ""
            for i in range(copies):
                ok, msg = print_image_usb(
                    str(out_path),
                    paper_width_px=PAPER_WIDTH,   # 576 고정
                )
                last_msg = msg
                if ok:
                    success_cnt += 1
                else:
                    # 한 장이라도 실패하면 바로 알리고 중단 (원하면 계속 시도하도록 바꿔도 됨)
                    self._set_status(f"{i+1}번째 출력 실패: {msg}", err=True)
                    break

            if success_cnt == copies:
                self._set_status(f"프린터 출력 완료 ({success_cnt}장)")
            else:
                self._set_status(f"프린터 일부만 출력됨 ({success_cnt}/{copies}) | {last_msg}", err=True)
        if self.chk_auto_reset.isChecked():
        # 프린터를 안 썼으면 바로 초기화, 썼으면 '모두 성공'한 경우에만 초기화
            printed_ok = (not self.chk_printer.isChecked()) or (success_cnt == copies)
            if printed_ok:
                QtCore.QTimer.singleShot(800, self._reset_all)  # 0.4초 뒤 초기화(컷팅 여유)
    # ---------- 초기화 / 공통 ----------
    def _reset_all(self):
        self.captured_images.clear()
        self.snap_btn.setText(f"촬영 (남은: {self.max_shots})")
        self._update_thumbs()
        self._set_status("초기화 완료")

    def _set_status(self, text: str, err: bool=False):
        self.status.setText(f"상태: {text}")
        self.status.setStyleSheet("color:#d33;" if err else "color:#08c;")

    def closeEvent(self, e: QtGui.QCloseEvent):
        try:
            self.timer.stop()
            if self.cap:
                self.cap.release()
        finally:
            super().closeEvent(e)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    w = BoothCam(); w.show()
    sys.exit(app.exec())
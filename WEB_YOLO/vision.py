"""
Thị giác máy tính: đọc camera, nhận diện màu bằng YOLO11, phân loại sản phẩm.

- Luồng camera: luôn giữ khung hình mới nhất (tránh trễ do bộ đệm webcam).
- Luồng YOLO: chạy nhận diện liên tục trên khung mới nhất, vẽ khung, mã hoá JPEG
  để phát lên web.
- classify(): khi ESP32 yêu cầu chụp, gom kết quả trên vài khung hình mới và
  bỏ phiếu ra một màu duy nhất.
"""
import logging
import os
import threading
import time

import cv2
import numpy as np
from ultralytics import YOLO

import config as cfg

log = logging.getLogger("vision")

# Màu khung vẽ (BGR) theo mã loại: 0 = LAM, 1 = ĐỎ, 2 = LỤC
BOX_COLORS = {0: (224, 123, 30), 1: (53, 57, 229), 2: (72, 157, 46)}
ROI_COLOR = (0, 215, 255)


def _make_placeholder(text):
    img = np.full((cfg.CAMERA_HEIGHT, cfg.CAMERA_WIDTH, 3), 40, np.uint8)
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
    cv2.putText(img, text, ((img.shape[1] - tw) // 2, (img.shape[0] + th) // 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (200, 200, 200), 2, cv2.LINE_AA)
    return img


def _encode(img):
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, cfg.JPEG_QUALITY])
    return buf.tobytes() if ok else b""


def roi_pixels(w, h):
    if not cfg.USE_ROI:
        return 0, 0, w, h
    x1, y1, x2, y2 = cfg.ROI
    return int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)


def legacy_rgb_classify(frame):
    """Thuật toán của phiên bản cũ (PyQt5): bỏ điểm ảnh tối, so sánh trung bình R/G/B trong ROI."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = roi_pixels(w, h)
    img = frame[y1:y2, x1:x2]
    dark = cv2.inRange(img, np.array([0, 0, 0]), np.array([90, 90, 90]))
    mask = dark == 0
    if not mask.any():
        return 0
    b, g, r = (float(img[..., i][mask].mean()) for i in range(3))
    if r > g:
        return 1 if r > b else 0
    return 2 if g > b + 2 else 0


class Vision:
    def __init__(self, source=cfg.CAMERA_SOURCE):
        self.source = source
        model_path = os.path.abspath(cfg.MODEL_PATH)
        log.info("Đang tải model YOLO: %s", model_path)
        self.model = YOLO(model_path)
        self.names = {int(k): str(v) for k, v in self.model.names.items()}
        self.cls_to_loai = {i: cfg.CLASS_TO_LOAI.get(n.lower()) for i, n in self.names.items()}
        log.info("Các lớp của model: %s", self.names)

        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._frame = None
        self._frame_id = 0
        self._dets = []
        self._det_frame = None
        self._result_id = 0
        self._jpeg = _encode(_make_placeholder("DANG KHOI DONG CAMERA..."))
        self._jpeg_id = 0
        self._no_cam_jpeg = _encode(_make_placeholder("KHONG MO DUOC CAMERA"))
        self.snapshot_jpeg = None

        self.camera_ok = False
        self.fps = 0.0
        self._cap = None
        self._running = True

        # Chạy thử 1 lần để lần nhận diện đầu tiên không bị chậm
        self.model.predict(np.zeros((cfg.CAMERA_HEIGHT, cfg.CAMERA_WIDTH, 3), np.uint8),
                           imgsz=cfg.IMG_SIZE, verbose=False)

        threading.Thread(target=self._capture_loop, daemon=True, name="camera").start()
        threading.Thread(target=self._infer_loop, daemon=True, name="yolo").start()

    # ------------------------------------------------------------ camera
    def _open_camera(self):
        src = self.source
        if isinstance(src, int) and os.name == "nt":
            cap = cv2.VideoCapture(src, cv2.CAP_DSHOW)   # mở nhanh hơn trên Windows
        else:
            cap = cv2.VideoCapture(src)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, cfg.CAMERA_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cfg.CAMERA_HEIGHT)
            log.info("Đã mở camera: %s", src)
            return cap
        cap.release()
        return None

    def _set_camera_lost(self):
        self.camera_ok = False
        with self._cond:
            self._jpeg = self._no_cam_jpeg
            self._jpeg_id += 1
            self._cond.notify_all()

    def _capture_loop(self):
        is_file = isinstance(self.source, str) and os.path.isfile(self.source)
        while self._running:
            if self._cap is None:
                self._cap = self._open_camera()
                if self._cap is None:
                    if self.camera_ok or self._jpeg_id == 0:
                        log.warning("Không mở được camera %s, thử lại sau 2 giây", self.source)
                    self._set_camera_lost()
                    time.sleep(2)
                    continue
            ok, frame = self._cap.read()
            if not ok or frame is None:
                if is_file:          # video thử nghiệm: phát lại từ đầu
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                log.warning("Mất tín hiệu camera")
                self._cap.release()
                self._cap = None
                self._set_camera_lost()
                time.sleep(1)
                continue
            if is_file:
                time.sleep(1 / 25)
            with self._lock:
                self._frame = frame
                self._frame_id += 1
            self.camera_ok = True

    # -------------------------------------------------------------- YOLO
    def _detect(self, frame):
        r = self.model.predict(frame, imgsz=cfg.IMG_SIZE, conf=cfg.CONF_THRESHOLD, verbose=False)[0]
        h, w = frame.shape[:2]
        rx1, ry1, rx2, ry2 = roi_pixels(w, h)
        dets = []
        boxes = r.boxes
        for (x1, y1, x2, y2), conf, cls in zip(boxes.xyxy.cpu().numpy(),
                                               boxes.conf.cpu().numpy(),
                                               boxes.cls.cpu().numpy().astype(int)):
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            dets.append({
                "box": (int(x1), int(y1), int(x2), int(y2)),
                "conf": float(conf),
                "cls": int(cls),
                "name": self.names.get(int(cls), str(cls)),
                "loai": self.cls_to_loai.get(int(cls)),
                "in_roi": rx1 <= cx <= rx2 and ry1 <= cy <= ry2,
            })
        return dets

    def _draw(self, frame, dets, highlight=None, show_fps=True):
        img = frame.copy()
        h, w = img.shape[:2]
        if cfg.USE_ROI:
            x1, y1, x2, y2 = roi_pixels(w, h)
            cv2.rectangle(img, (x1, y1), (x2 - 1, y2 - 1), ROI_COLOR, 1, cv2.LINE_AA)
            cv2.putText(img, "ROI", (x1 + 4, y1 + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        ROI_COLOR, 1, cv2.LINE_AA)
        for d in dets:
            color = BOX_COLORS.get(d["loai"], (200, 200, 200))
            if not d["in_roi"]:
                color = tuple(int(c * 0.5 + 64) for c in color)   # vật ngoài ROI: vẽ nhạt
            thick = 4 if d is highlight else (2 if d["in_roi"] else 1)
            x1, y1, x2, y2 = d["box"]
            cv2.rectangle(img, (x1, y1), (x2, y2), color, thick, cv2.LINE_AA)
            label = f'{d["name"]} {d["conf"]:.2f}'
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
            ty = max(y1, th + 6)
            cv2.rectangle(img, (x1, ty - th - 6), (x1 + tw + 6, ty), color, -1)
            cv2.putText(img, label, (x1 + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (255, 255, 255), 1, cv2.LINE_AA)
        if show_fps:
            cv2.putText(img, f"YOLO {self.fps:4.1f} FPS", (8, 22), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (255, 255, 255), 2, cv2.LINE_AA)
        return img

    def _infer_loop(self):
        last_id = -1
        last_t = None
        while self._running:
            with self._lock:
                frame, fid = self._frame, self._frame_id
            if frame is None or fid == last_id or not self.camera_ok:
                time.sleep(0.005)
                continue
            last_id = fid
            try:
                dets = self._detect(frame)
            except Exception:
                log.exception("Lỗi khi chạy YOLO")
                time.sleep(0.5)
                continue
            now = time.time()
            if last_t is not None:
                inst = 1.0 / max(now - last_t, 1e-3)
                self.fps = inst if self.fps == 0 else 0.9 * self.fps + 0.1 * inst
            last_t = now
            jpeg = _encode(self._draw(frame, dets))
            with self._cond:
                self._dets = dets
                self._det_frame = frame
                self._result_id += 1
                self._jpeg = jpeg
                self._jpeg_id += 1
                self._cond.notify_all()

    # ----------------------------------------------------------- dùng ngoài
    def wait_jpeg(self, last_id, timeout=1.0):
        """Chờ khung JPEG mới hơn last_id (dùng cho luồng video MJPEG)."""
        with self._cond:
            if self._jpeg_id == last_id:
                self._cond.wait(timeout)
            return self._jpeg_id, self._jpeg

    def classify(self):
        """
        Phân loại sản phẩm đang nằm trước camera.
        Trả về dict: loai, conf, method, frames, n_det.
        """
        deadline = time.time() + cfg.CLASSIFY_TIMEOUT
        with self._lock:
            last = self._result_id
        votes, best = {}, {}
        n_frames = 0
        while n_frames < cfg.CLASSIFY_FRAMES:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            with self._cond:
                if self._result_id == last:
                    self._cond.wait(remaining)
                if self._result_id == last:
                    continue
                last = self._result_id
                dets, frame = list(self._dets), self._det_frame
            n_frames += 1
            cands = [d for d in dets if d["in_roi"] and d["loai"] is not None]
            if not cands:
                continue
            d = max(cands, key=lambda x: x["conf"])
            votes[d["loai"]] = votes.get(d["loai"], 0.0) + d["conf"]
            if d["loai"] not in best or d["conf"] > best[d["loai"]][0]["conf"]:
                best[d["loai"]] = (d, frame, dets)

        if votes:
            loai = max(votes, key=votes.get)
            d, frame, dets = best[loai]
            self.snapshot_jpeg = _encode(self._draw(frame, dets, highlight=d, show_fps=False))
            return {"loai": loai, "conf": round(d["conf"], 3), "method": "YOLO",
                    "frames": n_frames, "votes": {str(k): round(v, 3) for k, v in votes.items()}}

        # Không có vật nào trong ROI -> phương án dự phòng
        with self._lock:
            frame = self._frame if self.camera_ok else None
        if frame is not None and cfg.FALLBACK_LEGACY_RGB:
            loai, method = legacy_rgb_classify(frame), "RGB (dự phòng)"
            self.snapshot_jpeg = _encode(self._draw(frame, [], show_fps=False))
        else:
            loai, method = cfg.FALLBACK_LOAI, "Mặc định (không có ảnh)"
        return {"loai": loai, "conf": None, "method": method, "frames": n_frames, "votes": {}}

    def close(self):
        self._running = False
        if self._cap is not None:
            self._cap.release()

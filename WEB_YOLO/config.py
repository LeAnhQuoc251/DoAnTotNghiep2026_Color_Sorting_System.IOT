"""
Cấu hình hệ thống phân loại sản phẩm theo màu sắc (YOLO11 + ESP32 + Web).
Chỉ cần sửa file này khi đổi cổng COM, camera, model hoặc vùng ROI.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ----------------------------- ESP32 (UART) -----------------------------
# Cổng COM nối với ESP32. Đặt "auto" để tự dò cổng USB-UART (CP210x/CH340).
SERIAL_PORT = "COM8"
SERIAL_BAUD = 9600

# ------------------------------- Camera --------------------------------
# Số thứ tự webcam (0, 1, ...) hoặc đường dẫn video / URL camera IP.
CAMERA_SOURCE = 0
CAMERA_WIDTH = 640
CAMERA_HEIGHT = 480

# -------------------------------- YOLO ---------------------------------
MODEL_PATH = os.path.join(BASE_DIR, "model", "best.pt")   # YOLO11n đã huấn luyện (Blue/Green/Red)
IMG_SIZE = 640            # kích thước ảnh lúc train
CONF_THRESHOLD = 0.5      # ngưỡng độ tin cậy

# Tên lớp trong best.pt  ->  mã "loai" gửi cho ESP32.
# Giữ đúng giao thức của phiên bản cũ (PyQt5): 1 = ĐỎ, 2 = LỤC, 0 = LAM.
CLASS_TO_LOAI = {"red": 1, "green": 2, "blue": 0}

LOAI_INFO = {
    1: {"key": "red",   "name": "ĐỎ",  "hex": "#e53935"},
    2: {"key": "green", "name": "LỤC", "hex": "#2e9d48"},
    0: {"key": "blue",  "name": "LAM", "hex": "#1e7be0"},
}

# Vùng quan tâm (ROI) theo tỉ lệ khung hình (x1, y1, x2, y2).
# Lấy từ phiên bản cũ (PyQt5): img[130:450, 160:515] trên ảnh 600x450.
# Chỉ những vật có tâm nằm trong ROI mới được dùng để phân loại.
USE_ROI = True
ROI = (160 / 600, 130 / 450, 515 / 600, 1.0)

# Khi ESP32 báo "chup = 1": gom kết quả YOLO trên N khung hình mới
# (tối đa T giây) rồi bỏ phiếu theo tổng độ tin cậy.
CLASSIFY_FRAMES = 3
CLASSIFY_TIMEOUT = 2.0

# Nếu YOLO không thấy vật nào: dùng thuật toán trung bình RGB cũ làm dự phòng
# để ESP32 không bị treo chờ kết quả. Đặt False để gửi FALLBACK_LOAI.
FALLBACK_LEGACY_RGB = True
FALLBACK_LOAI = 0

# --------------------------------- Web ---------------------------------
WEB_HOST = "0.0.0.0"      # 0.0.0.0 = cho phép máy khác trong mạng LAN truy cập
WEB_PORT = 5000
STREAM_FPS = 15
JPEG_QUALITY = 80
HISTORY_SIZE = 20         # số kết quả gần nhất giữ trong RAM (không dùng CSDL)

"""
HỆ THỐNG PHÂN LOẠI SẢN PHẨM THEO MÀU SẮC – YOLO11 + ESP32 + WEB

Chạy:  py -3.12 app.py            (hoặc nhấp đúp run.bat)
Mở:    http://localhost:5000      (máy khác trong LAN: http://<IP-máy-này>:5000)

Tuỳ chọn:  --port COM5 | auto     --camera 1     --web-port 8080
"""
import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from collections import deque
from datetime import datetime

from flask import Flask, Response, jsonify, send_from_directory

import config as cfg
from serial_link import ESP32Link
from vision import Vision

STATIC_DIR = os.path.join(cfg.BASE_DIR, "static")
app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static")
log = logging.getLogger("app")

vision: Vision = None
esp: ESP32Link = None

history = deque(maxlen=cfg.HISTORY_SIZE)   # chỉ lưu trong RAM, không dùng CSDL
last_result = None
_seq = 0
_classify_lock = threading.Lock()
_busy = False


# ------------------------------------------------------------------ phân loại
def run_classification(send_to_esp):
    """
    send_to_esp=True : ESP32 yêu cầu -> luôn chờ tới lượt (không được bỏ qua,
                       nếu không ESP32 sẽ treo chờ kết quả).
    send_to_esp=False: nút "Nhận diện thử" trên web -> bỏ qua nếu đang bận.
    """
    global last_result, _seq, _busy
    if not _classify_lock.acquire(blocking=send_to_esp):
        return None
    _busy = True
    try:
        t0 = time.time()
        res = vision.classify()
        sent = esp.send_result(res["loai"]) if send_to_esp else False
        info = cfg.LOAI_INFO[res["loai"]]
        _seq += 1
        res.update(
            id=_seq,
            time=datetime.now().strftime("%H:%M:%S"),
            color=info["key"], color_name=info["name"], hex=info["hex"],
            test=not send_to_esp, sent=sent,
            ms=int((time.time() - t0) * 1000),
        )
        last_result = res
        history.appendleft(res)
        log.info("Kết quả #%d: %s (%s, conf=%s)%s", _seq, info["name"], res["method"],
                 res["conf"], " -> đã gửi ESP32" if sent else "")
        return res
    finally:
        _busy = False
        _classify_lock.release()


def on_capture_request():
    threading.Thread(target=run_classification, args=(True,), daemon=True).start()


# ---------------------------------------------------------------------- routes
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/video_feed")
def video_feed():
    def gen():
        last = -1
        delay = 1.0 / cfg.STREAM_FPS
        while True:
            last, jpg = vision.wait_jpeg(last)
            yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                   + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
            time.sleep(delay)

    return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame",
                    headers={"Cache-Control": "no-store"})


@app.route("/snapshot.jpg")
def snapshot():
    if not vision.snapshot_jpeg:
        return Response(status=204)
    return Response(vision.snapshot_jpeg, mimetype="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@app.route("/api/status")
def api_status():
    return jsonify(
        esp=esp.snapshot(),
        camera={"ok": vision.camera_ok, "fps": round(vision.fps, 1), "source": str(vision.source)},
        model={"names": vision.names, "conf": cfg.CONF_THRESHOLD},
        busy=_busy,
        last=last_result,
        history=list(history),
        server_time=datetime.now().strftime("%H:%M:%S"),
    )


@app.route("/api/cmd/<name>", methods=["POST"])
def api_cmd(name):
    actions = {
        "mode": esp.toggle_mode,
        "start": esp.start,
        "stop": esp.stop,
        "gate1": lambda: esp.toggle_output("g1"),
        "gate2": lambda: esp.toggle_output("g2"),
        "conveyor": lambda: esp.toggle_output("bt"),
    }
    if name not in actions:
        return jsonify(ok=False, error="Lệnh không hợp lệ"), 404
    if not esp.connected:
        return jsonify(ok=False, error=f"Chưa kết nối ESP32 ({esp.port or esp.port_cfg})"), 503
    ok = actions[name]()
    return jsonify(ok=ok, error=None if ok else "Gửi lệnh tới ESP32 thất bại")


@app.route("/api/detect", methods=["POST"])
def api_detect():
    if not vision.camera_ok:
        return jsonify(ok=False, error="Camera chưa sẵn sàng"), 503
    res = run_classification(send_to_esp=False)
    if res is None:
        return jsonify(ok=False, error="Đang phân loại, thử lại sau"), 409
    return jsonify(ok=True, result=res)


@app.route("/api/exit", methods=["POST"])
def api_exit():
    if esp.connected:
        esp.stop()                     # dừng băng tải trước khi thoát cho an toàn
    threading.Timer(0.8, shutdown).start()
    return jsonify(ok=True)


def shutdown():
    log.info("Đang tắt hệ thống...")
    try:
        vision.close()
        esp.close()
    finally:
        os._exit(0)


# ------------------------------------------------------------------------ main
def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # không gửi gói tin nào, chỉ để chọn card mạng
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    global vision, esp
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Phân loại sản phẩm theo màu sắc - YOLO11 + ESP32")
    parser.add_argument("--port", default=cfg.SERIAL_PORT, help="cổng COM của ESP32 hoặc 'auto'")
    parser.add_argument("--camera", default=str(cfg.CAMERA_SOURCE), help="chỉ số webcam / file video / URL")
    parser.add_argument("--web-port", type=int, default=cfg.WEB_PORT)
    parser.add_argument("--open", action="store_true", help="tự mở trình duyệt khi server sẵn sàng")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    source = int(args.camera) if args.camera.lstrip("-").isdigit() else args.camera
    vision = Vision(source)
    esp = ESP32Link(args.port, cfg.SERIAL_BAUD, on_capture=on_capture_request)

    print("\n" + "=" * 60)
    print("  WEB ĐIỀU KHIỂN ĐÃ SẴN SÀNG")
    print(f"  Trên máy này : http://localhost:{args.web_port}")
    print(f"  Trong mạng LAN: http://{lan_ip()}:{args.web_port}")
    print("  Nhấn Ctrl+C để thoát")
    print("=" * 60 + "\n")

    if args.open:   # model và camera đã sẵn sàng -> mở trình duyệt ngay sau khi server chạy
        url = f"http://localhost:{args.web_port}"
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    try:
        app.run(host=cfg.WEB_HOST, port=args.web_port, threaded=True, use_reloader=False)
    finally:
        vision.close()
        esp.close()


if __name__ == "__main__":
    main()

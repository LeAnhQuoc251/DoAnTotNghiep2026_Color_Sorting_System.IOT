"""
Giao tiếp UART với ESP32 (giữ nguyên giao thức của phiên bản cũ PyQt5).

ESP32 -> PC (mỗi 500 ms và khi có sự kiện):
    mode|st|chup|sl_do|sl_luc|sl_lam[|g1|g2|bt]
    mode: 0 = AUTO, 1 = MANUAL      st: 0 = chờ, 1 = START, 2 = STOP
    chup = 1: sản phẩm đã tới cảm biến CB1, yêu cầu PC chụp và phân loại
    g1|g2|bt (tuỳ chọn, firmware mới): trạng thái gạt 1, gạt 2, băng tải

PC -> ESP32:  "<lệnh>|<giá trị>\\r\\n"
    a = chế độ, b = start(1)/stop(2), c = gạt 1, d = gạt 2, e = băng tải,
    f = kết quả phân loại (1 = ĐỎ, 2 = LỤC, 0 = LAM)
"""
import logging
import threading
import time

import serial
from serial.tools import list_ports

log = logging.getLogger("esp32")

_USB_UART_KEYWORDS = ("cp210", "ch340", "ch910", "ft232", "usb serial", "usb-serial", "uart")


class ESP32Link:
    def __init__(self, port, baud=9600, on_capture=None):
        self.port_cfg = port
        self.baud = baud
        self.on_capture = on_capture
        self.port = None
        self.error = ""
        self.last_rx = 0.0

        self.state = {"mode": 0, "st": 0, "sl_do": 0, "sl_luc": 0, "sl_lam": 0}
        self.outputs = {"g1": 0, "g2": 0, "bt": 0}
        self.outputs_from_esp = False     # True nếu firmware gửi kèm g1|g2|bt

        self._ser = None
        self._lock = threading.Lock()      # bảo vệ state/outputs
        self._wlock = threading.Lock()     # bảo vệ ghi cổng COM
        self._running = True
        threading.Thread(target=self._loop, daemon=True, name="serial").start()

    @property
    def connected(self):
        return self._ser is not None

    # ------------------------------------------------------------ kết nối
    def _resolve_port(self):
        if str(self.port_cfg).lower() != "auto":
            return self.port_cfg
        for p in list_ports.comports():
            text = f"{p.description} {p.hwid}".lower()
            if any(k in text for k in _USB_UART_KEYWORDS):
                return p.device
        return None

    def _close(self):
        with self._wlock:
            ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
            log.warning("Mất kết nối ESP32 (%s)", self.port)

    def _loop(self):
        buf = b""
        warned = False
        while self._running:
            if self._ser is None:
                port = self._resolve_port()
                try:
                    if not port:
                        raise serial.SerialException("không tìm thấy cổng USB-UART")
                    # serial_for_url: nhận "COM8" và cả "socket://ip:port", "loop://" (test)
                    ser = serial.serial_for_url(port, self.baud, timeout=0.1)
                    ser.reset_input_buffer()
                    self.port, self.error, buf, warned = port, "", b"", False
                    with self._wlock:
                        self._ser = ser
                    log.info("Đã kết nối ESP32 qua %s @ %d", port, self.baud)
                except (serial.SerialException, ValueError, OSError) as e:
                    self.port, self.error = port, str(e)
                    if not warned:
                        log.warning("Chưa kết nối được ESP32 (%s): %s. Sẽ tự thử lại.", port, e)
                        warned = True
                    time.sleep(2)
                    continue
            try:
                data = self._ser.read(self._ser.in_waiting or 1)
            except (serial.SerialException, OSError, AttributeError, TypeError):
                self._close()
                continue
            if not data:
                continue
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self._handle_line(line)
            if len(buf) > 512:            # rác (vd. log khởi động của ESP32)
                buf = b""

    def _handle_line(self, raw):
        text = raw.decode("ascii", errors="ignore").strip()
        parts = text.split("|")
        if len(parts) < 6:
            return
        try:
            vals = [int(p) for p in parts]
        except ValueError:
            return
        mode, st, chup, sl_do, sl_luc, sl_lam = vals[:6]
        with self._lock:
            self.state.update(mode=mode, st=st, sl_do=sl_do, sl_luc=sl_luc, sl_lam=sl_lam)
            if len(vals) >= 9:
                self.outputs.update(g1=vals[6], g2=vals[7], bt=vals[8])
                self.outputs_from_esp = True
        self.last_rx = time.time()
        if chup == 1:
            log.info("ESP32 yêu cầu chụp ảnh phân loại")
            if self.on_capture:
                self.on_capture()

    # -------------------------------------------------------------- gửi lệnh
    def send(self, key, value):
        msg = f"{key}|{value}\r\n".encode()
        with self._wlock:
            ser = self._ser
            if ser is None:
                return False
            try:
                ser.write(msg)
                ser.flush()
            except (serial.SerialException, OSError):
                ok = False
            else:
                ok = True
        if not ok:
            self._close()
        return ok

    def toggle_mode(self):
        new = 0 if self.state["mode"] == 1 else 1
        ok = self.send("a", new)
        if ok:
            with self._lock:      # ESP32 reset st, gạt, băng tải khi đổi chế độ
                self.state.update(mode=new, st=0)
                self.outputs.update(g1=0, g2=0, bt=0)
        return ok

    def start(self):
        ok = self.send("b", 1)
        if ok:
            self.state["st"] = 1
        return ok

    def stop(self):
        ok = self.send("b", 2)
        if ok:
            self.state["st"] = 2
        return ok

    def toggle_output(self, name):
        key = {"g1": "c", "g2": "d", "bt": "e"}[name]
        new = 0 if self.outputs[name] == 1 else 1
        ok = self.send(key, new)
        if ok:
            with self._lock:
                self.outputs[name] = new
        return ok

    def send_result(self, loai):
        return self.send("f", loai)

    def snapshot(self):
        with self._lock:
            return {
                "connected": self.connected,
                "port": self.port or str(self.port_cfg),
                "error": self.error,
                "last_rx_ago": round(time.time() - self.last_rx, 1) if self.last_rx else None,
                **self.state,
                "outputs": dict(self.outputs),
                "outputs_from_esp": self.outputs_from_esp,
            }

    def close(self):
        self._running = False
        self._close()

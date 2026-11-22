"""
Giao tiếp với ESP32 qua WiFi + MQTT (thay cho UART qua cáp USB).

Tiền tố topic <p> = MQTT_TOPIC trong config.py (phải trùng với ESP32):
    <p>/state    ESP32 -> PC  "mode|st|chup|sl_do|sl_luc|sl_lam|g1|g2|bt" mỗi 500 ms
                 mode: 0 = AUTO, 1 = MANUAL    st: 0 = chờ, 1 = START, 2 = STOP
                 chup = 1: đang chờ kết quả phân loại     g1|g2|bt: gạt 1, gạt 2, băng tải
    <p>/capture  ESP32 -> PC  mã yêu cầu chụp ảnh (sản phẩm đã tới CB1). ESP32 gửi lại
                 cùng mã mỗi 2 s tới khi có kết quả, PC không phân loại lại mà gửi lại kết quả cũ.
    <p>/status   ESP32 -> PC  "online" / "offline" (retained, LWT của broker)
    <p>/event    ESP32 -> PC  "reset" khi nhấn giữ nút GPIO18 5 s
    <p>/cmd      PC -> ESP32  "<lệnh>|<giá trị>[|<mã yêu cầu>]"
                 a = chế độ, b = start(1)/stop(2), c = gạt 1, d = gạt 2, e = băng tải,
                 f = kết quả phân loại (1 = ĐỎ, 2 = LỤC, 0 = LAM) kèm mã yêu cầu
"""
import logging
import threading
import time
import uuid

import paho.mqtt.client as mqtt

log = logging.getLogger("esp32")

STALE_AFTER = 5.0    # giây không nhận được trạng thái thì coi như mất ESP32


class ESP32Link:
    def __init__(self, host, port=1883, topic="csort/7f3a91", on_capture=None):
        self.host = host
        self.mqtt_port = port
        self.topic = topic.strip().rstrip("/")
        self.on_capture = on_capture
        self.port = f"MQTT {host}"        # chuỗi hiển thị trên web
        self.error = "đang kết nối broker"
        self.last_rx = 0.0
        self.broker_ok = False
        self.esp_online = False

        self.state = {"mode": 0, "st": 0, "chup": 0, "sl_do": 0, "sl_luc": 0, "sl_lam": 0}
        self.outputs = {"g1": 0, "g2": 0, "bt": 0}
        self.outputs_from_esp = False

        self._lock = threading.Lock()      # bảo vệ state/outputs
        self._req_lock = threading.Lock()  # bảo vệ mã yêu cầu chụp ảnh
        self._req_id = None
        self._req_result = None

        self._c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                              client_id=f"csort-pc-{uuid.uuid4().hex[:8]}")
        self._c.on_connect = self._on_connect
        self._c.on_connect_fail = self._on_connect_fail
        self._c.on_disconnect = self._on_disconnect
        self._c.on_message = self._on_message
        self._c.reconnect_delay_set(1, 10)
        self._c.connect_async(host, port, keepalive=15)
        self._c.loop_start()               # luồng nền, tự kết nối lại khi mất mạng

    def _t(self, name):
        return f"{self.topic}/{name}"

    @property
    def connected(self):
        """Đã vào broker và ESP32 đang gửi trạng thái đều đặn."""
        return self.broker_ok and time.time() - self.last_rx < STALE_AFTER

    @property
    def port_cfg(self):
        return self.port

    # ------------------------------------------------------------ MQTT
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            self.error = f"broker từ chối: {reason_code}"
            log.warning("MQTT broker %s từ chối kết nối: %s", self.host, reason_code)
            return
        self.broker_ok = True
        self.error = ""
        client.subscribe([(self._t("state"), 0), (self._t("capture"), 1),
                          (self._t("status"), 1), (self._t("event"), 1)])
        log.info("Đã kết nối MQTT broker %s:%d, topic %s/#", self.host, self.mqtt_port, self.topic)

    def _on_connect_fail(self, client, userdata):
        self.error = f"không kết nối được broker {self.host}"
        log.warning("Không kết nối được MQTT broker %s:%d. Sẽ tự thử lại.", self.host, self.mqtt_port)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        if self.broker_ok:
            log.warning("Mất kết nối MQTT broker (%s)", reason_code)
        self.broker_ok = False
        self.error = "mất kết nối broker"

    def _on_message(self, client, userdata, msg):
        text = msg.payload.decode("utf-8", errors="ignore").strip()
        name = msg.topic[len(self.topic) + 1:]
        if name == "state":
            self._handle_state(text)
        elif name == "capture":
            self._handle_capture(text)
        elif name == "status":
            online = text == "online"
            if online != self.esp_online:
                log.info("ESP32 %s", "online" if online else "offline")
            self.esp_online = online
            if online:
                with self._req_lock:        # ESP32 vừa khởi động / kết nối lại
                    self._req_id = self._req_result = None
            else:
                self.last_rx = 0.0
        elif name == "event" and text == "reset":
            log.warning("ESP32 báo RESET (nút GPIO18 được giữ 5 s), đang khởi động lại")
            self.last_rx = 0.0

    def _handle_state(self, text):
        parts = text.split("|")
        if len(parts) < 6:
            return
        try:
            vals = [int(p) for p in parts]
        except ValueError:
            return
        mode, st, chup, sl_do, sl_luc, sl_lam = vals[:6]
        with self._lock:
            self.state.update(mode=mode, st=st, chup=chup, sl_do=sl_do, sl_luc=sl_luc, sl_lam=sl_lam)
            if len(vals) >= 9:
                self.outputs.update(g1=vals[6], g2=vals[7], bt=vals[8])
                self.outputs_from_esp = True
        self.last_rx = time.time()
        self.esp_online = True

    def _handle_capture(self, text):
        try:
            rid = int(text)
        except ValueError:
            return
        with self._req_lock:
            repeat = rid == self._req_id
            result = self._req_result
            if not repeat:
                self._req_id, self._req_result = rid, None
        if not repeat:
            log.info("ESP32 yêu cầu chụp ảnh phân loại (#%d)", rid)
            if self.on_capture:
                self.on_capture(rid)
        elif result is not None:
            log.info("ESP32 gửi lại yêu cầu #%d, gửi lại kết quả", rid)
            self.send("f", result, rid)
        # nếu đang phân loại yêu cầu này thì bỏ qua, kết quả sẽ được gửi khi xong

    # -------------------------------------------------------------- gửi lệnh
    def send(self, key, value, req_id=None):
        if not self.broker_ok:
            return False
        payload = f"{key}|{value}" if req_id is None else f"{key}|{value}|{req_id}"
        info = self._c.publish(self._t("cmd"), payload, qos=1)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

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
            with self._lock:
                self.state["st"] = 1
        return ok

    def stop(self):
        ok = self.send("b", 2)
        if ok:
            with self._lock:
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

    def send_result(self, loai, req_id):
        with self._req_lock:
            if req_id == self._req_id:
                self._req_result = loai      # để gửi lại nếu ESP32 hỏi lại
        return self.send("f", loai, req_id)

    def snapshot(self):
        with self._lock:
            if self.connected:
                error = ""
            elif not self.broker_ok:
                error = self.error
            else:
                error = "chờ ESP32 kết nối WiFi/MQTT"
            return {
                "connected": self.connected,
                "port": self.port,
                "error": error,
                "broker_ok": self.broker_ok,
                "topic": self.topic,
                "last_rx_ago": round(time.time() - self.last_rx, 1) if self.last_rx else None,
                **self.state,
                "outputs": dict(self.outputs),
                "outputs_from_esp": self.outputs_from_esp,
            }

    def close(self):
        self.broker_ok = False             # tắt chủ động, không cảnh báo mất kết nối
        try:
            self._c.disconnect()
        finally:
            self._c.loop_stop()

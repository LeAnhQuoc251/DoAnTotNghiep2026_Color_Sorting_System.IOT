/*
 * ĐỒ ÁN TỐT NGHIỆP 2026 – HỆ THỐNG PHÂN LOẠI SẢN PHẨM THEO MÀU SẮC
 * Sinh viên thực hiện: Lê Anh Quốc
 *
 * Firmware ESP32 (DOIT ESP32 DevKit V1): điều khiển băng tải, 2 servo gạt,
 * đọc 3 cảm biến vật cản và trao đổi dữ liệu với máy tính qua WiFi + MQTT
 * (không cần cáp USB). Máy tính chạy WEB_YOLO nhận diện màu bằng YOLO11.
 *
 * Chân kết nối:
 *   CB1 = GPIO26  cảm biến vị trí chụp ảnh (băng tải dừng để camera nhận diện)
 *   CB2 = GPIO27  cảm biến trước gạt 1 (sản phẩm ĐỎ)
 *   CB3 = GPIO14  cảm biến trước gạt 2 (sản phẩm LỤC) và cuối băng tải (LAM)
 *   BT  = GPIO19  điều khiển động cơ băng tải (mức 1 = chạy)
 *   Servo gạt 1 = GPIO25, servo gạt 2 = GPIO13
 *   NÚT = GPIO18  nhấn giữ 5 s: reset hệ thống (dừng băng tải, xoá bộ đếm, khởi động lại)
 *                 tiếp tục giữ thêm 3 s sau khi khởi động lại: vào chế độ cài đặt WiFi
 *   LED = GPIO33  đèn báo trạng thái kết nối:
 *                 sáng liên tục   = đã kết nối MQTT, hệ thống sẵn sàng
 *                 nháy chậm 1 Hz  = có WiFi, đang kết nối MQTT broker
 *                 nháy nhanh      = mất WiFi / đang kết nối WiFi
 *                 nháy đôi        = chế độ cài đặt WiFi (phát WiFi "ColorSort-Setup")
 *                 nháy rất nhanh  = đang giữ nút, sắp reset
 *
 * MQTT (tiền tố <p> mặc định "csort/7f3a91", phải trùng MQTT_TOPIC trong WEB_YOLO/config.py):
 *   <p>/state    ESP32 -> PC  mode|st|chup|sl_do|sl_luc|sl_lam|g1|g2|bt  (mỗi 500 ms và khi có sự kiện)
 *   <p>/capture  ESP32 -> PC  mã yêu cầu chụp ảnh; gửi lại mỗi 2 s tới khi nhận kết quả
 *   <p>/status   ESP32 -> PC  "online" / "offline" (retained, LWT)
 *   <p>/event    ESP32 -> PC  "reset" khi nhấn giữ nút reset
 *   <p>/cmd      PC -> ESP32  <lệnh>|<giá trị>[|<mã yêu cầu>]
 *     a = chế độ (0 AUTO, 1 MANUAL)   b = 1 START, 2 STOP
 *     c = gạt 1   d = gạt 2   e = băng tải   f = kết quả (1 ĐỎ, 2 LỤC, 0 LAM) kèm mã yêu cầu
 *
 * Thư viện: ESP32Servo, PubSubClient (các thư viện WiFi, WebServer, DNSServer,
 * Preferences có sẵn trong lõi ESP32).
 */
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>

// ----------------------- cấu hình mặc định (đổi được trên trang cài đặt WiFi) -----------------------
#define MQTT_BROKER_MAC_DINH  "broker.emqx.io"
#define MQTT_PORT_MAC_DINH    1883
#define MQTT_TOPIC_MAC_DINH   "csort/7f3a91"
#define AP_TEN                "ColorSort-Setup"   // WiFi do ESP32 phát ở chế độ cài đặt
#define AP_MAT_KHAU           "12345678"

// ---------------------------------------------- chân -----------------------------------------------
#define CB1 26
#define CB2 27
#define CB3 14

#define BT        19
#define NUT_RESET 18
#define NUT_NHAN  LOW     // nút nối GPIO18 với GND, dùng điện trở kéo lên bên trong
#define LED_TT    33
#define LED_SANG  HIGH    // LED nối GPIO33 -> điện trở -> GND

#define TG_GIU_RESET    5000   // giữ nút 5 s để reset
#define TG_GIU_CAI_DAT  3000   // giữ nút khi khởi động 3 s để vào cài đặt WiFi

#define thu   175   // góc servo 1 ở vị trí thu về
#define gat   130   // góc servo 1 khi gạt sản phẩm
#define thu2  180   // góc servo 2 ở vị trí thu về
#define gat2  130   // góc servo 2 khi gạt sản phẩm
#define BAT   1
#define TAT   0

Servo servo1;
Servo servo2;

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);
Preferences prefs;
WebServer web(80);
DNSServer dns;

String wifi_ssid, wifi_pass, mqtt_host, mqtt_topic;
uint16_t mqtt_port = MQTT_PORT_MAC_DINH;
String t_state, t_capture, t_status, t_event, t_cmd;
char mqtt_id[32];
String ds_wifi;                   // danh sách WiFi quét được (trang cài đặt)
bool che_do_cai_dat = false;

int time_gat = 2000;              // thời gian giữ servo ở vị trí gạt (ms)
char mang[40];
int xong = 0;                     // 1 = đã nhận kết quả phân loại từ PC
int loai = 0, modee = 0;          // loai: 1 ĐỎ, 2 LỤC, 0 LAM; modee: 0 AUTO, 1 MANUAL
int sl_luc = 0, sl_lam = 0, sl_do = 0, st = 0, g1 = 0, g2 = 0, chup = 0, bt = 0;
uint32_t ma_yc = 0;               // mã yêu cầu chụp ảnh hiện tại
unsigned long time_gui = 0, time_thu_mqtt = 0, t_nhan = 0;
bool dang_nhan = false;

//*****************************************************************************************//
void setup() {
  Serial.begin(115200);           // chỉ dùng để xem log khi cần, không còn dùng để truyền dữ liệu
  pinMode(CB1, INPUT_PULLUP);
  pinMode(CB2, INPUT_PULLUP);
  pinMode(CB3, INPUT_PULLUP);
  pinMode(NUT_RESET, INPUT_PULLUP);
  pinMode(LED_TT, OUTPUT);
  den(false);
  pinMode(BT, OUTPUT);
  digitalWrite(BT, TAT);
  servo1.attach(25);
  servo2.attach(13);
  servo1.write(thu);
  servo2.write(thu2);

  doc_cau_hinh();
  if (wifi_ssid.length() == 0 || giu_nut_khi_khoi_dong()) {
    chay_cai_dat();               // không quay lại, lưu xong sẽ khởi động lại
  }
  ket_noi_wifi();
}
//*****************************************************************************************//
void loop() {
  phuc_vu();
  stopp();
  if (modee == 0) {
    Auto();
  }
  else {
    Manual();
  }
}
//*****************************************************************************************//
// Chế độ AUTO: băng tải chạy, sản phẩm tới CB1 thì dừng và yêu cầu PC phân loại,
// sau đó gạt sản phẩm vào đúng ngăn theo kết quả nhận được.
void Auto() {
  if (st == 1) {
    digitalWrite(BT, BAT);
    if (digitalRead(CB1) == 0) {
      cho(100);
      digitalWrite(BT, TAT);
      cho(500);
      ma_yc++;
      xong = 0;
      chup = 1;
      gui_yeu_cau();
      gui_du_lieu();
      unsigned long t_yc = millis();
      while (xong == 0) {
        phuc_vu();
        stopp();
        if (modee != 0) {         // đổi sang MANUAL trong lúc chờ: huỷ yêu cầu
          chup = 0;
          return;
        }
        if (millis() - t_yc >= 2000) {   // chưa có kết quả: gửi lại yêu cầu (phòng mất gói)
          gui_yeu_cau();
          t_yc = millis();
        }
        delay(2);
      }
      chup = 0;
      gui_du_lieu();
      digitalWrite(BT, BAT);
      while (digitalRead(CB1) == 0) {
        cho(100);
        stopp();
      }
      cho(400);
    }
    if (loai == 1) {
      if (digitalRead(CB2) == 0) {
        servo1.write(gat);
        cho(time_gat);
        servo1.write(thu);
        sl_do++;
        cho(200);
        gui_du_lieu();
      }
    }
    else if (loai == 2) {
      if (digitalRead(CB3) == 0) {
        servo2.write(gat2);
        cho(time_gat);
        servo2.write(thu2);
        sl_luc++;
        cho(200);
        gui_du_lieu();
      }
    }
    else {
      if (digitalRead(CB3) == 0) {
        while (digitalRead(CB3) == 0) {
          digitalWrite(BT, BAT);
          cho(100);
          stopp();
        }
        sl_lam++;
        cho(1000);
        gui_du_lieu();
      }
    }
  }
}

//*****************************************************************************************//
// Chế độ MANUAL: sau khi START, điều khiển trực tiếp 2 servo gạt và băng tải từ web.
void Manual() {
  if (st == 1) {
    if (g1 == 0) {
      servo1.write(thu);
    }
    else {
      servo1.write(gat);
    }

    if (g2 == 0) {
      servo2.write(thu2);
    }
    else {
      servo2.write(gat2);
    }

    if (bt == 0) {
      digitalWrite(BT, TAT);
    }
    else {
      digitalWrite(BT, BAT);
    }
  }
}
//*****************************************************************************************//
// Khi nhận lệnh STOP: dừng băng tải và chờ tới khi có lệnh mới
void stopp() {
  while (st == 2) {
    phuc_vu();
    digitalWrite(BT, TAT);
    delay(2);
  }
}
//*****************************************************************************************//
// Việc nền gọi liên tục ở mọi vòng chờ: giữ kết nối WiFi/MQTT, nhận lệnh,
// gửi trạng thái định kỳ, đọc nút reset và cập nhật đèn báo.
void phuc_vu() {
  if (WiFi.status() == WL_CONNECTED) {
    if (mqtt.connected()) {
      mqtt.loop();
    }
    else if (time_thu_mqtt == 0 || millis() - time_thu_mqtt >= 3000) {
      time_thu_mqtt = millis();
      ket_noi_mqtt();
    }
  }
  gui_du_lieu2();
  nut_bam();
  cap_nhat_den();
}
//*****************************************************************************************//
// Thay cho delay(): vẫn nhận lệnh, giữ kết nối và đọc nút trong lúc chờ
void cho(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    phuc_vu();
    delay(2);
  }
}
//*****************************************************************************************//
// Khung dữ liệu gửi lên PC: mode|st|chup|sl_do|sl_luc|sl_lam|g1|g2|bt
void gui_du_lieu() {
  if (!mqtt.connected()) return;
  char buf[48];
  snprintf(buf, sizeof(buf), "%d|%d|%d|%d|%d|%d|%d|%d|%d",
           modee, st, chup, sl_do, sl_luc, sl_lam, g1, g2, bt);
  mqtt.publish(t_state.c_str(), buf);
}
//*****************************************************************************************//
void gui_du_lieu2() {
  if (millis() - time_gui >= 500) {
    gui_du_lieu();
    time_gui = millis();
  }
}
//*****************************************************************************************//
// Yêu cầu PC chụp ảnh và phân loại sản phẩm đang nằm ở CB1
void gui_yeu_cau() {
  if (!mqtt.connected()) return;
  char buf[12];
  snprintf(buf, sizeof(buf), "%lu", (unsigned long)ma_yc);
  mqtt.publish(t_capture.c_str(), buf);
  Serial.printf("Yeu cau phan loai #%lu\n", (unsigned long)ma_yc);
}
//*****************************************************************************************//
// Nhận lệnh từ máy tính qua topic <p>/cmd: "<lệnh>|<giá trị>[|<mã yêu cầu>]"
void nhan_lenh(char *topic, byte *payload, unsigned int len) {
  if (len >= sizeof(mang)) len = sizeof(mang) - 1;
  memcpy(mang, payload, len);
  mang[len] = 0;
  char *lenh = strtok(mang, "|\r\n");
  char *gia_tri = strtok(NULL, "|\r\n");
  char *ma = strtok(NULL, "|\r\n");
  if (lenh == NULL || gia_tri == NULL) return;
  int v = atoi(gia_tri);

  if (strcmp(lenh, "a") == 0) {
    modee = v;
    st = 0;
    digitalWrite(BT, TAT);
    bt = 0;
    g1 = 0;
    g2 = 0;
  }
  else if (strcmp(lenh, "b") == 0) st = v;
  else if (strcmp(lenh, "c") == 0) g1 = v;
  else if (strcmp(lenh, "d") == 0) g2 = v;
  else if (strcmp(lenh, "e") == 0) bt = v;
  else if (strcmp(lenh, "f") == 0) {
    // chỉ nhận kết quả khi đang chờ và đúng mã yêu cầu (bỏ qua kết quả cũ gửi lặp)
    if (chup == 1 && (ma == NULL || strtoul(ma, NULL, 10) == ma_yc)) {
      loai = v;
      xong = 1;
    }
  }
}
//*****************************************************************************************//
void ket_noi_wifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);           // giảm độ trễ nhận lệnh
  WiFi.setAutoReconnect(true);
  WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str());
  Serial.printf("WiFi: dang ket noi \"%s\"\n", wifi_ssid.c_str());

  uint8_t mac[6];
  WiFi.macAddress(mac);
  snprintf(mqtt_id, sizeof(mqtt_id), "csort-esp32-%02X%02X%02X", mac[3], mac[4], mac[5]);
  t_state = mqtt_topic + "/state";
  t_capture = mqtt_topic + "/capture";
  t_status = mqtt_topic + "/status";
  t_event = mqtt_topic + "/event";
  t_cmd = mqtt_topic + "/cmd";
  mqtt.setServer(mqtt_host.c_str(), mqtt_port);
  mqtt.setCallback(nhan_lenh);
  mqtt.setKeepAlive(10);
  mqtt.setSocketTimeout(3);
  ma_yc = esp_random() % 100000;  // mã khác nhau sau mỗi lần khởi động
}
//*****************************************************************************************//
void ket_noi_mqtt() {
  Serial.printf("MQTT: ket noi %s:%u ... ", mqtt_host.c_str(), mqtt_port);
  // LWT: broker tự báo "offline" cho PC nếu ESP32 mất kết nối đột ngột
  if (mqtt.connect(mqtt_id, t_status.c_str(), 1, true, "offline")) {
    Serial.println("OK");
    mqtt.publish(t_status.c_str(), "online", true);
    mqtt.subscribe(t_cmd.c_str(), 1);
    gui_du_lieu();
    if (chup == 1) gui_yeu_cau();   // đang chờ kết quả thì gửi lại yêu cầu
  }
  else {
    Serial.printf("loi %d\n", mqtt.state());
  }
}
//*****************************************************************************************//
// Nút GPIO18: nhấn giữ 5 s thì reset hệ thống
void nut_bam() {
  if (digitalRead(NUT_RESET) != NUT_NHAN) {
    dang_nhan = false;
    return;
  }
  if (!dang_nhan) {
    dang_nhan = true;
    t_nhan = millis();
    return;
  }
  if (millis() - t_nhan >= TG_GIU_RESET) {
    reset_he_thong();
  }
}
//*****************************************************************************************//
// Dừng băng tải, đưa servo về vị trí thu, báo cho PC rồi khởi động lại ESP32
// (bộ đếm và chế độ trở về mặc định: AUTO, chờ START).
void reset_he_thong() {
  Serial.println("Reset he thong (giu nut 5 s)");
  digitalWrite(BT, TAT);
  servo1.write(thu);
  servo2.write(thu2);
  if (mqtt.connected()) {
    mqtt.publish(t_event.c_str(), "reset");
    mqtt.publish(t_status.c_str(), "offline", true);
    mqtt.loop();
    delay(100);
    mqtt.disconnect();
  }
  den(false);
  delay(300);
  ESP.restart();
}
//*****************************************************************************************//
void den(bool sang) {
  digitalWrite(LED_TT, sang ? LED_SANG : !LED_SANG);
}

void cap_nhat_den() {
  unsigned long t = millis();
  bool sang;
  if (dang_nhan && t - t_nhan >= 500) {
    sang = (t / 50) % 2;                       // đang giữ nút: nháy rất nhanh
  }
  else if (che_do_cai_dat) {
    unsigned long p = t % 1200;                // nháy đôi
    sang = p < 100 || (p >= 250 && p < 350);
  }
  else if (WiFi.status() != WL_CONNECTED) {
    sang = (t / 150) % 2;                      // mất WiFi: nháy nhanh
  }
  else if (!mqtt.connected()) {
    sang = (t / 500) % 2;                      // chưa vào broker: nháy chậm
  }
  else {
    sang = true;                               // sẵn sàng
  }
  den(sang);
}
//*****************************************************************************************//
// ------------------------------- cấu hình WiFi / MQTT ------------------------------------//
void doc_cau_hinh() {
  prefs.begin("csort", true);
  wifi_ssid = prefs.getString("ssid", "");
  wifi_pass = prefs.getString("pass", "");
  mqtt_host = prefs.getString("host", MQTT_BROKER_MAC_DINH);
  mqtt_port = prefs.getUShort("port", MQTT_PORT_MAC_DINH);
  mqtt_topic = prefs.getString("topic", MQTT_TOPIC_MAC_DINH);
  prefs.end();
  if (mqtt_host.length() == 0) mqtt_host = MQTT_BROKER_MAC_DINH;
  if (mqtt_topic.length() == 0) mqtt_topic = MQTT_TOPIC_MAC_DINH;
  if (mqtt_port == 0) mqtt_port = MQTT_PORT_MAC_DINH;
}

// Nút đang được giữ lúc khởi động (thường là ngay sau khi reset bằng nút):
// giữ tiếp 3 s (đèn sáng liên tục) thì vào chế độ cài đặt, thả sớm thì chạy bình thường.
bool giu_nut_khi_khoi_dong() {
  if (digitalRead(NUT_RESET) != NUT_NHAN) return false;
  unsigned long t0 = millis();
  while (digitalRead(NUT_RESET) == NUT_NHAN) {
    den(true);
    if (millis() - t0 >= TG_GIU_CAI_DAT) return true;
    delay(10);
  }
  den(false);
  return false;
}

String html(const String &s) {
  String r;
  for (unsigned int i = 0; i < s.length(); i++) {
    char c = s[i];
    if (c == '&') r += "&amp;";
    else if (c == '<') r += "&lt;";
    else if (c == '>') r += "&gt;";
    else if (c == '"') r += "&quot;";
    else if (c == '\'') r += "&#39;";
    else r += c;
  }
  return r;
}

void trang_cai_dat() {
  String p;
  p.reserve(3000);
  p += F("<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>Cài đặt ESP32</title><style>"
         "body{font-family:system-ui,sans-serif;background:#f4f6f8;margin:0;padding:16px;color:#1d2733}"
         "form{max-width:420px;margin:auto;background:#fff;padding:20px;border-radius:12px;box-shadow:0 2px 10px #0001}"
         "h2{margin:0 0 4px}p{color:#5b6b7b;margin:0 0 16px;font-size:14px}"
         "label{display:block;font-size:14px;margin:12px 0 4px;font-weight:600}"
         "input{width:100%;box-sizing:border-box;padding:10px;border:1px solid #c9d2dc;border-radius:8px;font-size:16px}"
         "button{margin-top:20px;width:100%;padding:12px;border:0;border-radius:8px;background:#1e7be0;color:#fff;font-size:16px;font-weight:600}"
         "small{color:#5b6b7b}</style></head><body><form method='post' action='/luu'>"
         "<h2>Cài đặt kết nối ESP32</h2><p>Hệ thống phân loại sản phẩm theo màu sắc</p>"
         "<label>Tên WiFi</label><input name='ssid' list='ds' required value='");
  p += html(wifi_ssid);
  p += F("'><datalist id='ds'>");
  p += ds_wifi;
  p += F("</datalist><label>Mật khẩu WiFi</label>"
         "<input name='pass' type='password' placeholder='để trống nếu WiFi không có mật khẩu'>"
         "<label>MQTT broker</label><input name='host' required value='");
  p += html(mqtt_host);
  p += F("'><small>Tên miền hoặc IP, ví dụ broker.emqx.io hoặc IP máy tính chạy Mosquitto</small>"
         "<label>Cổng MQTT</label><input name='port' type='number' min='1' max='65535' value='");
  p += String(mqtt_port);
  p += F("'><label>Tiền tố topic</label><input name='topic' required value='");
  p += html(mqtt_topic);
  p += F("'><small>Phải trùng MQTT_TOPIC trong WEB_YOLO/config.py</small>"
         "<button type='submit'>Lưu và khởi động lại</button></form></body></html>");
  web.send(200, "text/html; charset=utf-8", p);
}

void luu_cai_dat() {
  String ssid = web.arg("ssid");
  String host = web.arg("host");
  String topic = web.arg("topic");
  ssid.trim();
  host.trim();
  topic.trim();
  while (topic.endsWith("/")) topic.remove(topic.length() - 1);
  long port = web.arg("port").toInt();
  if (ssid.length() == 0 || host.length() == 0 || topic.length() == 0 ||
      topic.indexOf('#') >= 0 || topic.indexOf('+') >= 0 || port < 1 || port > 65535) {
    web.send(400, "text/plain; charset=utf-8", "Thông tin không hợp lệ, hãy quay lại và nhập lại.");
    return;
  }
  prefs.begin("csort", false);
  prefs.putString("ssid", ssid);
  prefs.putString("pass", web.arg("pass"));
  prefs.putString("host", host);
  prefs.putUShort("port", (uint16_t)port);
  prefs.putString("topic", topic);
  prefs.end();
  web.send(200, "text/html; charset=utf-8",
           "<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
           "<body style='font-family:system-ui;padding:24px'><h3>Đã lưu.</h3>"
           "<p>ESP32 đang khởi động lại và kết nối WiFi \"" + html(ssid) + "\". "
           "Đèn GPIO33 sáng liên tục là đã kết nối xong.</p></body>");
  delay(1500);
  ESP.restart();
}

// Chế độ cài đặt: ESP32 phát WiFi "ColorSort-Setup" (mật khẩu 12345678), mở trang
// http://192.168.4.1 để nhập WiFi và MQTT broker. Hàm này không quay lại.
void chay_cai_dat() {
  che_do_cai_dat = true;
  Serial.println("Che do cai dat WiFi: ket noi WiFi \"" AP_TEN "\", mo http://192.168.4.1");
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_TEN, AP_MAT_KHAU);
  delay(100);
  int n = WiFi.scanNetworks();
  for (int i = 0; i < n; i++) {
    ds_wifi += "<option value=\"" + html(WiFi.SSID(i)) + "\">";
  }
  dns.start(53, "*", WiFi.softAPIP());   // điện thoại tự bật trang cài đặt
  web.on("/", HTTP_GET, trang_cai_dat);
  web.on("/luu", HTTP_POST, luu_cai_dat);
  web.onNotFound([]() {
    web.sendHeader("Location", "http://192.168.4.1/");
    web.send(302, "text/plain", "");
  });
  web.begin();

  unsigned long t0 = millis();
  while (true) {
    dns.processNextRequest();
    web.handleClient();
    nut_bam();                          // giữ 5 s: thoát cài đặt, khởi động lại
    cap_nhat_den();
    // đã có WiFi lưu sẵn mà không ai cài đặt trong 5 phút: khởi động lại chạy bình thường
    if (wifi_ssid.length() > 0 && millis() - t0 > 300000UL) ESP.restart();
    delay(2);
  }
}

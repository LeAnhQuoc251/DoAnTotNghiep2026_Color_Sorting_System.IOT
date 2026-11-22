/*
 * ĐỒ ÁN TỐT NGHIỆP 2026 – HỆ THỐNG PHÂN LOẠI SẢN PHẨM THEO MÀU SẮC
 * Sinh viên thực hiện: Lê Anh Quốc
 *
 * Firmware ESP32 (DOIT ESP32 DevKit V1): điều khiển băng tải, 2 servo gạt,
 * đọc 3 cảm biến vật cản và trao đổi dữ liệu với máy tính qua UART 9600 baud.
 * Toàn bộ giám sát và điều khiển từ xa được thực hiện trên trang web do máy
 * tính phục vụ (thư mục WEB_YOLO), ESP32 không cần WiFi hay dịch vụ đám mây.
 *
 * Chân kết nối:
 *   CB1 = GPIO26  cảm biến vị trí chụp ảnh (băng tải dừng để camera nhận diện)
 *   CB2 = GPIO27  cảm biến trước gạt 1 (sản phẩm ĐỎ)
 *   CB3 = GPIO14  cảm biến trước gạt 2 (sản phẩm LỤC) và cuối băng tải (LAM)
 *   BT  = GPIO19  điều khiển động cơ băng tải (mức 1 = chạy)
 *   Servo gạt 1 = GPIO25, servo gạt 2 = GPIO13
 *
 * ESP32 -> PC (mỗi 500 ms và khi có sự kiện):
 *   mode|st|chup|sl_do|sl_luc|sl_lam|g1|g2|bt
 * PC -> ESP32:  <lệnh>|<giá trị>\r\n
 *   a = chế độ (0 AUTO, 1 MANUAL)   b = 1 START, 2 STOP
 *   c = gạt 1   d = gạt 2   e = băng tải   f = kết quả (1 ĐỎ, 2 LỤC, 0 LAM)
 */
#include <ESP32Servo.h>

Servo servo1;
Servo servo2;

#define CB1 26
#define CB2 27
#define CB3 14

#define BT    19
#define thu   175   // góc servo 1 ở vị trí thu về
#define gat   130   // góc servo 1 khi gạt sản phẩm
#define thu2  180   // góc servo 2 ở vị trí thu về
#define gat2  130   // góc servo 2 khi gạt sản phẩm
#define BAT   1
#define TAT   0

int time_gat = 2000;          // thời gian giữ servo ở vị trí gạt (ms)
String dataa = "";
char mang[20];
char *token1, *token2;
int xong = 0;                 // 1 = đã nhận kết quả phân loại từ PC
int loai = 0, modee = 0;      // loai: 1 ĐỎ, 2 LỤC, 0 LAM; modee: 0 AUTO, 1 MANUAL
int sl_luc = 0, sl_lam = 0, sl_do = 0, st = 0, g1 = 0, g2 = 0, chup = 0, bt = 0;
unsigned long int time_gui = 0;

//*****************************************************************************************//
void setup() {
  Serial.begin(9600);
  pinMode(CB1, INPUT_PULLUP);
  pinMode(CB2, INPUT_PULLUP);
  pinMode(CB3, INPUT_PULLUP);
  pinMode(BT, OUTPUT);
  digitalWrite(BT, TAT);
  servo1.attach(25);
  servo2.attach(13);
  servo1.write(thu);
  servo2.write(thu2);
  gui_du_lieu2();
  delay(500);
}
//*****************************************************************************************//
void loop() {
  stopp();
  gui_du_lieu2();
  if (modee == 0) {
    Auto();
  }
  else {
    Manual();
  }
}
//*****************************************************************************************//
// Nhận lệnh từ máy tính: "<lệnh>|<giá trị>"
void serialEvent() {
  while (Serial.available()) {
    dataa = Serial.readStringUntil('\n');
    dataa.toCharArray(mang, 20);
    token1 = strtok(mang, "|");
    token2 = strtok(NULL, "|");
    if (token1 == NULL || token2 == NULL) continue;
    String st1(token1);
    String st2(token2);
    if (st1 == "a") {
      modee = st2.toInt();
      st = 0;
      digitalWrite(BT, TAT);
      bt = 0;
      g1 = 0;
      g2 = 0;
    }
    if (st1 == "b") st = st2.toInt();
    if (st1 == "c") g1 = st2.toInt();
    if (st1 == "d") g2 = st2.toInt();
    if (st1 == "e") bt = st2.toInt();
    if (st1 == "f") {
      loai = st2.toInt();
      xong = 1;
    }
  }
}
//*****************************************************************************************//
// Chế độ AUTO: băng tải chạy, sản phẩm tới CB1 thì dừng và yêu cầu PC phân loại,
// sau đó gạt sản phẩm vào đúng ngăn theo kết quả nhận được.
void Auto() {
  if (st == 1) {
    digitalWrite(BT, BAT);
    if (digitalRead(CB1) == 0) {
      delay(100);
      digitalWrite(BT, TAT);
      delay(500);
      chup = 1;
      xong = 0;
      gui_du_lieu();
      chup = 0;
      while (xong == 0) {
        serialEvent();
        chup = 0;
        stopp();
      }
      digitalWrite(BT, BAT);
      while (digitalRead(CB1) == 0) {
        serialEvent();
        delay(100);
        stopp();
      }
      delay(400);
    }
    if (loai == 1) {
      if (digitalRead(CB2) == 0) {
        servo1.write(gat);
        delay(time_gat);
        servo1.write(thu);
        sl_do++;
        delay(200);
        gui_du_lieu();
      }
    }
    else if (loai == 2) {
      if (digitalRead(CB3) == 0) {
        servo2.write(gat2);
        delay(time_gat);
        servo2.write(thu2);
        sl_luc++;
        delay(200);
        gui_du_lieu();
      }
    }
    else {
      if (digitalRead(CB3) == 0) {
        while (digitalRead(CB3) == 0) {
          digitalWrite(BT, BAT);
          delay(100);
          stopp();
        }
        sl_lam++;
        delay(1000);
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
// Khung dữ liệu gửi lên PC: mode|st|chup|sl_do|sl_luc|sl_lam|g1|g2|bt
// (3 trường cuối dùng cho web hiển thị trạng thái gạt 1, gạt 2, băng tải ở chế độ MANUAL)
void gui_du_lieu() {
  Serial.print(modee);
  Serial.print("|");
  Serial.print(st);
  Serial.print("|");
  Serial.print(chup);
  Serial.print("|");
  Serial.print(sl_do);
  Serial.print("|");
  Serial.print(sl_luc);
  Serial.print("|");
  Serial.print(sl_lam);
  Serial.print("|");
  Serial.print(g1);
  Serial.print("|");
  Serial.print(g2);
  Serial.print("|");
  Serial.println(bt);
}
//*****************************************************************************************//
void gui_du_lieu2() {
  if (millis() - time_gui >= 500) {
    gui_du_lieu();
    time_gui = millis();
    //0|1|0|2|2|2|0|0|0
  }
}
//*****************************************************************************************//
// Khi nhận lệnh STOP: dừng băng tải và chờ tới khi có lệnh mới
void stopp() {
  while (st == 2) {
    serialEvent();
    digitalWrite(BT, TAT);
    gui_du_lieu2();
  }
}

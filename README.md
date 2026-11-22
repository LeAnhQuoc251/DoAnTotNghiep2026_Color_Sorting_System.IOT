# Đồ án tốt nghiệp 2026: Hệ thống phân loại sản phẩm theo màu sắc

Sinh viên thực hiện: **Lê Anh Quốc**

Hệ thống dùng **thị giác máy tính (YOLO11)** để nhận diện màu sản phẩm (đỏ, lục, lam) trên băng tải. **ESP32** điều khiển băng tải và servo gạt, trao đổi dữ liệu với máy tính **không dây qua WiFi + MQTT** (không cần cáp USB). Toàn bộ hệ thống được giám sát và điều khiển qua một **trang web** trên máy tính và điện thoại trong cùng mạng WiFi, không dùng cơ sở dữ liệu.

```
 Webcam ──► Laptop (WEB_YOLO/app.py) ◄── MQTT ──► broker ◄── MQTT/WiFi ──► ESP32 ──► băng tải, 2 servo gạt
            ├─ Luồng camera                                                     cảm biến CB1, CB2, CB3
            ├─ Luồng YOLO11 (Blue/Green/Red)                                    nút reset GPIO18, LED GPIO33
            └─ Flask web :5000 ──► trình duyệt (máy tính / điện thoại cùng mạng WiFi)
```

> Nhánh `main` là phiên bản cũ giao tiếp UART qua cáp USB. Nhánh `mqtt` (tài liệu này) thay UART bằng WiFi + MQTT.

Tài liệu đi kèm: [submission.md](submission.md) (mô tả chi tiết đồ án) và file báo cáo `BaoCao_DATN_LeAnhQuoc.docx`.

## Cấu trúc thư mục

```
DoAnTotNghiep2026/
├── README.md               Tài liệu này (hướng dẫn cài đặt, chạy, xử lý sự cố)
├── submission.md           Mô tả chi tiết toàn bộ đồ án
├── BaoCao_DATN_LeAnhQuoc.docx  Báo cáo đồ án tốt nghiệp
├── WEB_YOLO/               Phần mềm trên laptop: YOLO + giao tiếp ESP32 + web
│   ├── run.bat             Nhấp đúp để chạy hệ thống
│   ├── app.py              Chương trình chính: web server Flask, ghép camera, YOLO và ESP32
│   ├── vision.py           Đọc camera, chạy YOLO, vẽ khung, phân loại (bỏ phiếu trên nhiều khung hình)
│   ├── mqtt_link.py        Giao tiếp MQTT với ESP32, tự kết nối lại khi mất mạng
│   ├── config.py           Cấu hình: MQTT broker/topic, camera, ngưỡng tin cậy, ROI...
│   ├── requirements.txt    Thư viện Python cần cài
│   ├── model/best.pt       Model YOLO11n đã huấn luyện (3 lớp: Blue, Green, Red)
│   └── static/             Giao diện web (HTML, CSS, JS thuần, không cần Internet)
├── ESP32_FIRMWARE/         Firmware ESP32 (Arduino)
│   └── ESP32_FIRMWARE.ino  Điều khiển AUTO/MANUAL, servo, cảm biến, WiFi + MQTT, nút reset, đèn báo
└── PCB/PCB.pdsprj          Mạch điện tử (Proteus)
```

## Cài đặt (chỉ làm một lần)

Máy cần Python 3.12 (đã có sẵn trên laptop). Lệnh `python` trên máy đang trỏ tới Python của MSYS2, vì vậy hãy dùng `py -3.12`:

```bat
cd WEB_YOLO
py -3.12 -m pip install -r requirements.txt
```

## Kết nối ESP32 với WiFi (lần đầu hoặc khi đổi mạng)

1. Cấp nguồn cho ESP32. Lần đầu (chưa lưu WiFi) ESP32 tự vào **chế độ cài đặt**: đèn GPIO33 **nháy đôi** và ESP32 phát WiFi **`ColorSort-Setup`** (mật khẩu `12345678`).
2. Dùng điện thoại/laptop vào WiFi đó, trang cài đặt sẽ tự bật (nếu không, mở `http://192.168.4.1`).
3. Chọn tên WiFi, nhập mật khẩu. Giữ nguyên MQTT broker `broker.emqx.io`, cổng `1883`, tiền tố topic `csort/7f3a91` (phải trùng `MQTT_TOPIC` trong `WEB_YOLO/config.py`). Bấm **Lưu và khởi động lại**.
4. ESP32 khởi động lại và kết nối. Đèn GPIO33 **sáng liên tục** là đã sẵn sàng.

Muốn đổi WiFi sau này: **giữ nút GPIO18 khoảng 8 giây** (5 s đầu hệ thống reset, giữ tiếp 3 s khi đèn sáng liên tục thì vào chế độ cài đặt).
ESP32 không vào được WiFi 5 GHz. Laptop chạy web chỉ cần có Internet, không bắt buộc cùng WiFi với ESP32.

## Nút bấm GPIO18 và đèn GPIO33

| Thao tác / Đèn | Ý nghĩa |
|---|---|
| Nhấn giữ nút **5 s** | **Reset hệ thống**: dừng băng tải, đưa 2 servo về vị trí thu, báo cho máy tính, khởi động lại ESP32 (bộ đếm về 0, chế độ AUTO, chờ START). Trong lúc giữ, đèn nháy rất nhanh |
| Giữ tiếp **3 s** sau khi reset | Vào chế độ cài đặt WiFi/MQTT |
| Đèn **sáng liên tục** | Đã kết nối MQTT, hệ thống sẵn sàng |
| Đèn **nháy chậm** (1 lần/giây) | Có WiFi nhưng chưa vào được MQTT broker |
| Đèn **nháy nhanh** | Chưa kết nối được WiFi (sai mật khẩu, mất sóng...) |
| Đèn **nháy đôi** | Chế độ cài đặt WiFi |

Firmware giả định nút nối GPIO18 với GND (dùng điện trở kéo lên bên trong) và LED nối GPIO33 → điện trở → GND. Nếu mạch nối ngược, đổi `NUT_NHAN` / `LED_SANG` ở đầu file `.ino`.

## Chạy hệ thống

1. Cấp nguồn cho ESP32 (không cần cắm cáp USB vào laptop), chờ đèn GPIO33 sáng liên tục. Cắm webcam vào laptop.
2. Nhấp đúp **`WEB_YOLO\run.bat` trong File Explorer** của Windows. Nếu nhấp đúp trong VS Code thì VS Code chỉ mở file để sửa chứ không chạy. Trong VS Code có thể chuột phải vào file → *Reveal in File Explorer*, hoặc gõ `.\WEB_YOLO\run.bat` ở Terminal.
   Sau khoảng 5–10 giây (thời gian tải model YOLO), trình duyệt sẽ tự mở `http://localhost:5000`. Cửa sổ đen của `run.bat` phải được giữ mở trong lúc dùng web. Nếu `run.bat` đang chạy sẵn, nhấp đúp lần nữa chỉ mở lại trình duyệt.
3. Để mở trên điện thoại hoặc máy khác cùng WiFi, dùng địa chỉ in ra trên cửa sổ, ví dụ `http://192.168.0.103:5000`.
   - Laptop và điện thoại vào cùng một mạng, ví dụ điểm phát WiFi của điện thoại. ESP32 liên lạc với laptop qua MQTT broker nên không cần biết IP của laptop.
   - Nếu mạng WiFi chặn các thiết bị kết nối với nhau (thường gặp ở WiFi công cộng), hãy dùng điểm phát WiFi của điện thoại.
   - Với broker công cộng, laptop và ESP32 đều cần Internet. Muốn chạy không cần Internet, xem phần *Dùng broker trong mạng LAN*.
   - Lần chạy đầu tiên Windows sẽ hỏi quyền tường lửa: chọn **Allow** (Private network).
   - Nếu mạng WiFi đang đặt là *Public*, mở CMD bằng quyền Admin và chạy:
     `netsh advfirewall firewall add rule name="DATN Web" dir=in action=allow protocol=TCP localport=5000`
4. Tắt hệ thống: bấm **THOÁT** trên web (băng tải sẽ dừng trước) hoặc đóng cửa sổ `run.bat`. Chỉ đóng trình duyệt thì chương trình vẫn chạy.

Có thể đổi tham số mà không cần sửa code:

```bat
run.bat --broker 192.168.1.10   :: đổi MQTT broker (vd. Mosquitto trong mạng LAN)
run.bat --topic csort/abc123    :: đổi tiền tố topic (phải trùng với ESP32)
run.bat --camera 1           :: dùng webcam thứ 2 (camera 0 = webcam nhìn băng tải, 1 = camera trước của laptop)
run.bat --web-port 8080
```

## Chức năng trên web so với phiên bản cũ (PyQt5 + xử lý ảnh RGB)

| Phiên bản cũ (PyQt5) | Web | Lệnh MQTT (`<p>/cmd`) |
|---|---|---|
| `lb_cam`: hình camera | **Camera trực tiếp**, có vẽ khung YOLO và vùng ROI | |
| `lb_im`: ảnh đã xử lý | **Ảnh chụp lúc phân loại** (khung được chọn tô đậm) | |
| `lb_mau`: ĐỎ / LỤC / LAM | **Kết quả phân loại**: màu, độ tin cậy, phương pháp, thời gian | `f\|loai\|mã` |
| `BT_MODE`: AUTO/MANUAL | Nút **CHẾ ĐỘ** (xanh = AUTO, cam = MANUAL) | `a\|0/1` |
| `BT_START` / `BT_STOP` | **START** / **STOP** | `b\|1` / `b\|2` |
| `lb_st`: đèn trạng thái | Đèn **CHỜ / ĐANG CHẠY / ĐÃ DỪNG** | |
| `lb_do`, `lb_luc`, `lb_lam` | **Bộ đếm** ĐỎ / LỤC / LAM và tổng | |
| `BT_T1`, `BT_T2`, `BT_BT` | **GẠT 1, GẠT 2, BĂNG TẢI** (hiện trạng thái BẬT/TẮT) | `c`, `d`, `e` |
| `THOAT` | **THOÁT**: dừng băng tải rồi tắt chương trình | `b\|2` |
| Không có | **Nhận diện thử**: chạy YOLO trên khung hiện tại, không gửi kết quả cho ESP32 | |
| Không có | **Lịch sử** 20 lần nhận diện gần nhất (lưu trong RAM) | |
| Không có | Trạng thái kết nối ESP32 / Camera, FPS | |

Nút điều khiển tay chỉ bấm được ở chế độ MANUAL, giống logic `Manual()` của ESP32: phải nhấn START thì lệnh gạt và băng tải mới có tác dụng.

## Thuật toán phân loại bằng YOLO

1. Luồng YOLO chạy liên tục trên khung hình mới nhất (YOLO11n trên CPU đạt khoảng 12 đến 18 FPS).
2. Khi ESP32 gửi yêu cầu chụp lên topic `<p>/capture` (sản phẩm đã tới CB1 và băng tải đã dừng), chương trình lấy kết quả của **3 khung hình mới** (tối đa 2 giây).
3. Ở mỗi khung, chỉ xét các vật có **tâm nằm trong ROI** (vùng `img[130:450, 160:515]` của phiên bản cũ, khung vàng trên web) và chọn vật có độ tin cậy cao nhất.
4. **Bỏ phiếu** theo tổng độ tin cậy của từng màu, sau đó gửi `f|loai|mã` về ESP32 (Red→1, Green→2, Blue→0).
5. Nếu YOLO không thấy vật nào, chương trình dùng **thuật toán trung bình RGB của phiên bản cũ** làm dự phòng để ESP32 không bị treo chờ. Web sẽ ghi rõ "RGB (dự phòng)".

Các thông số trên nằm trong `WEB_YOLO/config.py`: `CONF_THRESHOLD`, `ROI`, `USE_ROI`, `CLASSIFY_FRAMES`, `CLASSIFY_TIMEOUT`, `FALLBACK_LEGACY_RGB`.
Nếu camera bị dời chỗ, xem lại khung vàng trên web và chỉnh `ROI` cho phù hợp.

**Kết quả chạy thật (18/11/2026):** chạy AUTO với sản phẩm 3 màu, tất cả được phân loại đúng bằng YOLO. Độ tin cậy 0.94–0.98, mỗi lần phân loại mất khoảng 150–270 ms.

## Giao thức MQTT

Tiền tố topic `<p>` mặc định `csort/7f3a91` (`MQTT_TOPIC` trong `config.py`, ô *Tiền tố topic* trên trang cài đặt ESP32).

| Topic | Chiều | Nội dung |
|---|---|---|
| `<p>/state` | ESP32 → PC | `mode\|st\|chup\|sl_do\|sl_luc\|sl_lam\|g1\|g2\|bt`, mỗi 500 ms và khi có sự kiện |
| `<p>/capture` | ESP32 → PC | Mã yêu cầu chụp ảnh. Gửi lại mỗi 2 s tới khi có kết quả; PC nhận ra mã trùng thì gửi lại kết quả cũ, không phân loại lại |
| `<p>/status` | ESP32 → PC | `online` / `offline` (retained; broker tự gửi `offline` khi ESP32 mất kết nối đột ngột) |
| `<p>/event` | ESP32 → PC | `reset` khi nhấn giữ nút 5 s |
| `<p>/cmd` | PC → ESP32 | `<lệnh>\|<giá trị>[\|<mã>]` với lệnh `a`…`f` như bảng ở trên (QoS 1) |

`mode` 0 = AUTO, 1 = MANUAL · `st` 0 = chờ, 1 = START, 2 = STOP · `chup` 1 = đang chờ kết quả phân loại · `g1|g2|bt`: trạng thái gạt 1, gạt 2, băng tải.
Web báo ESP32 mất kết nối nếu quá 5 s không nhận được `<p>/state`.

### Dùng broker trong mạng LAN (không cần Internet)

Broker công cộng `broker.emqx.io` tiện nhưng ai biết topic cũng đọc/gửi được lệnh, và cần Internet. Muốn chạy riêng trong LAN:
cài [Mosquitto](https://mosquitto.org/download/) trên laptop, thêm vào `mosquitto.conf` hai dòng `listener 1883` và `allow_anonymous true`,
mở cổng 1883 trên tường lửa, đặt `MQTT_BROKER = "localhost"` trong `config.py`, rồi vào trang cài đặt ESP32 nhập IP của laptop làm MQTT broker.

## Firmware ESP32

- Board: **DOIT ESP32 DevKit V1** (`esp32:esp32:esp32doit-devkit-v1`), chip ESP32-D0WD-V3, lõi ESP32 3.3.8.
- Thư viện cần có: **ESP32Servo**, **PubSubClient** (Nick O'Leary). WiFi, WebServer, DNSServer, Preferences có sẵn trong lõi ESP32.
- Cáp USB chỉ cần khi nạp firmware. Log gỡ lỗi vẫn in ra Serial 115200 baud nếu cắm cáp.
- Cổng COM8 là mạch **FTDI FT232R**. Với mạch này, nút Upload của Arduino IDE / `arduino-cli upload` hay báo lỗi
  `Failed to connect to ESP32: Invalid head of packet`. Gọi **esptool trực tiếp** thì nạp được, và không cần bấm nút BOOT.

Lệnh nạp, chạy trong CMD tại thư mục `DoAnTotNghiep2026`:

```bat
set CLI="C:\Program Files\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
set ESPTOOL="%LOCALAPPDATA%\Arduino15\packages\esp32\tools\esptool_py\5.2.0\esptool.exe"
set APP0="%LOCALAPPDATA%\Arduino15\packages\esp32\hardware\esp32\3.3.8\tools\partitions\boot_app0.bin"
set B=%TEMP%\esp32_build

%CLI% compile --fqbn esp32:esp32:esp32doit-devkit-v1 --build-path %B% ESP32_FIRMWARE
%ESPTOOL% --chip esp32 --port COM8 --baud 115200 write-flash -z ^
  0x1000 %B%\ESP32_FIRMWARE.ino.bootloader.bin 0x8000 %B%\ESP32_FIRMWARE.ino.partitions.bin ^
  0xe000 %APP0% 0x10000 %B%\ESP32_FIRMWARE.ino.bin
```

Muốn xoá sạch bộ nhớ ESP32 trước khi nạp, chạy thêm `%ESPTOOL% --chip esp32 --port COM8 --baud 115200 erase-flash` trước lệnh `write-flash`.

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| Web báo "ESP32 · chờ ESP32 kết nối WiFi/MQTT" | Xem đèn GPIO33: nháy nhanh = sai WiFi (giữ nút ~8 s để cài lại); nháy chậm = ESP32 không vào được broker; sáng liên tục = kiểm tra tiền tố topic hai bên có trùng không |
| Web báo "ESP32 · không kết nối được broker" | Laptop không có Internet hoặc sai `MQTT_BROKER` trong `config.py` |
| "Camera · không có tín hiệu" | Đóng ứng dụng khác đang dùng webcam (Zoom, Camera...) hoặc thử `--camera 1` |
| Nhận diện sai hoặc hay rơi vào "RGB (dự phòng)" | Kiểm tra ánh sáng, chỉnh `ROI` hoặc giảm `CONF_THRESHOLD` (ví dụ 0.4) trong `config.py` |
| Điện thoại không mở được web | Điện thoại phải cùng WiFi với laptop. Kiểm tra tường lửa (xem phần Chạy hệ thống) |
| Báo lỗi "No module named ..." | Chạy bằng `py -3.12` (hoặc `run.bat`), không dùng `python` |

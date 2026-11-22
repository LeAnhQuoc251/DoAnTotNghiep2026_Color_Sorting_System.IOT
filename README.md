# Đồ án tốt nghiệp 2026: Hệ thống phân loại sản phẩm theo màu sắc

Sinh viên thực hiện: **Lê Anh Quốc**

Hệ thống dùng **thị giác máy tính (YOLO11)** để nhận diện màu sản phẩm (đỏ, lục, lam) trên băng tải. **ESP32** điều khiển băng tải và servo gạt theo lệnh từ máy tính qua cáp USB (UART). Toàn bộ hệ thống được giám sát và điều khiển qua một **trang web** trên máy tính và điện thoại trong cùng mạng WiFi, không dùng ứng dụng hay dịch vụ đám mây bên ngoài, không dùng cơ sở dữ liệu.

```
 Webcam ──► Laptop (WEB_YOLO/app.py) ──── USB/UART 9600 ────► ESP32 ──► băng tải, 2 servo gạt
            ├─ Luồng camera                                              cảm biến CB1, CB2, CB3
            ├─ Luồng YOLO11 (Blue/Green/Red)
            └─ Flask web :5000 ──► trình duyệt (máy tính / điện thoại cùng mạng WiFi)
```

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
│   ├── serial_link.py      Giao tiếp UART với ESP32, tự kết nối lại khi rút/cắm cáp
│   ├── config.py           Cấu hình: cổng COM, camera, ngưỡng tin cậy, ROI...
│   ├── requirements.txt    Thư viện Python cần cài
│   ├── model/best.pt       Model YOLO11n đã huấn luyện (3 lớp: Blue, Green, Red)
│   └── static/             Giao diện web (HTML, CSS, JS thuần, không cần Internet)
├── ESP32_FIRMWARE/         Firmware ESP32 (Arduino)
│   └── ESP32_FIRMWARE.ino  Điều khiển AUTO/MANUAL, servo, cảm biến, giao tiếp UART với máy tính
└── PCB/PCB.pdsprj          Mạch điện tử (Proteus)
```

## Cài đặt (chỉ làm một lần)

Máy cần Python 3.12 (đã có sẵn trên laptop). Lệnh `python` trên máy đang trỏ tới Python của MSYS2, vì vậy hãy dùng `py -3.12`:

```bat
cd WEB_YOLO
py -3.12 -m pip install -r requirements.txt
```

## Chạy hệ thống

1. Cắm ESP32 (mặc định **COM8**) và webcam. **Đóng Serial Monitor của Arduino IDE**, vì hai chương trình không thể dùng chung một cổng COM.
2. Nhấp đúp **`WEB_YOLO\run.bat` trong File Explorer** của Windows. Nếu nhấp đúp trong VS Code thì VS Code chỉ mở file để sửa chứ không chạy. Trong VS Code có thể chuột phải vào file → *Reveal in File Explorer*, hoặc gõ `.\WEB_YOLO\run.bat` ở Terminal.
   Sau khoảng 5–10 giây (thời gian tải model YOLO), trình duyệt sẽ tự mở `http://localhost:5000`. Cửa sổ đen của `run.bat` phải được giữ mở trong lúc dùng web. Nếu `run.bat` đang chạy sẵn, nhấp đúp lần nữa chỉ mở lại trình duyệt.
3. Để mở trên điện thoại hoặc máy khác cùng WiFi, dùng địa chỉ in ra trên cửa sổ, ví dụ `http://192.168.0.103:5000`.
   - ESP32 **không dùng WiFi**. Chỉ cần laptop và điện thoại vào cùng một mạng, ví dụ điểm phát WiFi của điện thoại. Khi đổi sang mạng khác, không phải cấu hình lại gì, chỉ cần đọc lại địa chỉ mới trên cửa sổ `run.bat`.
   - Nếu mạng WiFi chặn các thiết bị kết nối với nhau (thường gặp ở WiFi công cộng), hãy dùng điểm phát WiFi của điện thoại.
   - Không có mạng thì vẫn dùng được đầy đủ trên laptop tại `http://localhost:5000`.
   - Lần chạy đầu tiên Windows sẽ hỏi quyền tường lửa: chọn **Allow** (Private network).
   - Nếu mạng WiFi đang đặt là *Public*, mở CMD bằng quyền Admin và chạy:
     `netsh advfirewall firewall add rule name="DATN Web" dir=in action=allow protocol=TCP localport=5000`
4. Tắt hệ thống: bấm **THOÁT** trên web (băng tải sẽ dừng trước) hoặc đóng cửa sổ `run.bat`. Chỉ đóng trình duyệt thì chương trình vẫn chạy.

Có thể đổi tham số mà không cần sửa code:

```bat
run.bat --port COM5          :: đổi cổng ESP32 (hoặc --port auto để tự dò)
run.bat --camera 1           :: dùng webcam thứ 2 (camera 0 = webcam nhìn băng tải, 1 = camera trước của laptop)
run.bat --web-port 8080
```

## Chức năng trên web so với phiên bản cũ (PyQt5 + xử lý ảnh RGB)

| Phiên bản cũ (PyQt5) | Web | Lệnh UART |
|---|---|---|
| `lb_cam`: hình camera | **Camera trực tiếp**, có vẽ khung YOLO và vùng ROI | |
| `lb_im`: ảnh đã xử lý | **Ảnh chụp lúc phân loại** (khung được chọn tô đậm) | |
| `lb_mau`: ĐỎ / LỤC / LAM | **Kết quả phân loại**: màu, độ tin cậy, phương pháp, thời gian | `f\|loai` |
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
2. Khi ESP32 gửi `chup = 1` (sản phẩm đã tới CB1 và băng tải đã dừng), chương trình lấy kết quả của **3 khung hình mới** (tối đa 2 giây).
3. Ở mỗi khung, chỉ xét các vật có **tâm nằm trong ROI** (vùng `img[130:450, 160:515]` của phiên bản cũ, khung vàng trên web) và chọn vật có độ tin cậy cao nhất.
4. **Bỏ phiếu** theo tổng độ tin cậy của từng màu, sau đó gửi `f|loai` về ESP32 (Red→1, Green→2, Blue→0).
5. Nếu YOLO không thấy vật nào, chương trình dùng **thuật toán trung bình RGB của phiên bản cũ** làm dự phòng để ESP32 không bị treo chờ. Web sẽ ghi rõ "RGB (dự phòng)".

Các thông số trên nằm trong `WEB_YOLO/config.py`: `CONF_THRESHOLD`, `ROI`, `USE_ROI`, `CLASSIFY_FRAMES`, `CLASSIFY_TIMEOUT`, `FALLBACK_LEGACY_RGB`.
Nếu camera bị dời chỗ, xem lại khung vàng trên web và chỉnh `ROI` cho phù hợp.

**Kết quả chạy thật (18/11/2026):** chạy AUTO với sản phẩm 3 màu, tất cả được phân loại đúng bằng YOLO. Độ tin cậy 0.94–0.98, mỗi lần phân loại mất khoảng 150–270 ms.

## Giao thức UART (9600 baud)

**ESP32 → PC**, gửi mỗi 500 ms và khi có sự kiện:

```
mode|st|chup|sl_do|sl_luc|sl_lam|g1|g2|bt
```

`mode` 0 = AUTO, 1 = MANUAL · `st` 0 = chờ, 1 = START, 2 = STOP · `chup` 1 = yêu cầu chụp · `g1|g2|bt`: trạng thái gạt 1, gạt 2, băng tải.

**PC → ESP32**: `<lệnh>|<giá trị>\r\n` với lệnh `a`, `b`, `c`, `d`, `e`, `f` như bảng ở trên.

## Firmware ESP32

- Board: **DOIT ESP32 DevKit V1** (`esp32:esp32:esp32doit-devkit-v1`), chip ESP32-D0WD-V3, lõi ESP32 3.3.8.
- Thư viện cần có: **ESP32Servo**. Firmware không dùng WiFi, Bluetooth hay dịch vụ đám mây; mọi điều khiển đi qua UART từ máy tính.
- Cổng COM8 là mạch **FTDI FT232R**. Với mạch này, nút Upload của Arduino IDE / `arduino-cli upload` hay báo lỗi
  `Failed to connect to ESP32: Invalid head of packet`. Gọi **esptool trực tiếp** thì nạp được, và không cần bấm nút BOOT.
  Trước khi nạp, nhớ tắt web (nút THOÁT), vì web đang giữ cổng COM8.

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
| Web báo "ESP32 · chưa kết nối (COM8)" | Kiểm tra cáp. Đóng Serial Monitor. Xem cổng trong Device Manager rồi chạy `run.bat --port COMx` |
| "Camera · không có tín hiệu" | Đóng ứng dụng khác đang dùng webcam (Zoom, Camera...) hoặc thử `--camera 1` |
| Nhận diện sai hoặc hay rơi vào "RGB (dự phòng)" | Kiểm tra ánh sáng, chỉnh `ROI` hoặc giảm `CONF_THRESHOLD` (ví dụ 0.4) trong `config.py` |
| Điện thoại không mở được web | Điện thoại phải cùng WiFi với laptop. Kiểm tra tường lửa (xem phần Chạy hệ thống) |
| Báo lỗi "No module named ..." | Chạy bằng `py -3.12` (hoặc `run.bat`), không dùng `python` |

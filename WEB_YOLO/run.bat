@echo off
chcp 65001 >nul
title He thong phan loai mau sac - YOLO11 + ESP32
cd /d "%~dp0"
rem Khong tao thu muc __pycache__ de giu thu muc gon gang
set PYTHONDONTWRITEBYTECODE=1

rem Neu he thong dang chay san thi chi mo trinh duyet, khong chay ban thu hai
netstat -ano | findstr /R /C:":5000 .*LISTENING" >nul
if %errorlevel%==0 (
    echo He thong dang chay san. Dang mo trinh duyet...
    start "" http://localhost:5000
    timeout /t 3 >nul
    exit /b
)

echo Dang khoi dong he thong: tai model YOLO, mo camera, ket noi ESP32...
echo Trinh duyet se tu mo khi san sang. Dong cua so nay hoac bam THOAT tren web de tat.
echo.
where py >nul 2>nul
if %errorlevel%==0 (
    py -3.12 app.py --open %*
) else (
    python app.py --open %*
)
echo.
echo Chuong trinh da dung.
pause

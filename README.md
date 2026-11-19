# Tondar Download Manager (تندر)

دانلود منیجر برای Ubuntu 22.04 / 24.04 / 25.x / 26.04 با چیدمان و روال کاری شبیه IDM.

## قابلیت‌ها
- دانلود چندتکه‌ای تا ۳۲ کانکشن با **تقسیم پویا** (کانکشنی که تمام شد، بزرگ‌ترین تکه‌ی باقی‌مانده را نصف می‌کند)
- Pause / Resume کامل (حتی بعد از بستن برنامه یا قطع برق)
- صف دانلود (Main queue)، **Scheduler** با ساعت شروع/پایان، روزهای هفته و خاموش کردن سیستم بعد از اتمام
- **Speed Limiter** سراسری
- دسته‌بندی خودکار: Compressed / Documents / Music / Programs / Video با پوشه‌ی جدا
- پنجره‌های Download File Info، پیشرفت با نقشه‌ی تکه‌ها و لیست کانکشن‌ها، Download complete
- **افزونه‌ی مرورگر** (Chrome / Chromium / Brave / Edge / Vivaldi / Firefox):
  - گرفتن خودکار دانلودهای مرورگر
  - دکمه‌ی **«Download this video»** روی پلیر YouTube و سایت‌های دیگر، با منوی کیفیت (1080p, 720p, ..., M4A, MP3)
  - تشخیص فایل‌های ویدیو/صوت/استریم (m3u8) در هر صفحه
  - منوی راست‌کلیک: Download with Tondar، Download all links
- پشتیبانی از HTTP/HTTPS/FTP، پروکسی HTTP و SOCKS5، کوکی و Referer از مرورگر، Basic Auth
- نظارت روی کلیپ‌بورد، آیکن در System Tray، اجرای خودکار هنگام ورود به سیستم

## نصب
```bash
sudo apt install ./tondar_1.0.1_all.deb
```
بعد از نصب، از منوی برنامه‌ها «Tondar Download Manager» را باز کنید.

### نصب افزونه
**Chrome / Chromium / Brave / Edge:**
1. به `chrome://extensions` بروید و **Developer mode** را روشن کنید.
2. **Load unpacked** را بزنید و پوشه‌ی `/usr/share/tondar/extension/chrome` را انتخاب کنید.

**Firefox:** افزونه‌ی امضاشده موقع نصب بسته از طریق `/etc/firefox/policies/policies.json` خودکار نصب می‌شود. فقط یک بار Firefox را ببندید و باز کنید، بعد روی آیکن Tondar بزنید و «Allow access to all websites» را بزنید.

### یوتیوب
اولین باری که ویدیو دانلود می‌کنید، برنامه آخرین نسخه‌ی yt-dlp و Deno را (که یوتیوب الان لازم دارد) در `~/.local/share/tondar/bin` دانلود می‌کند و هر هفته به‌روزش می‌کند.
اگر GitHub در دسترس نیست، اول در Options > Proxy / Socks پروکسی را تنظیم کنید و بعد Downloads > Update video engine را بزنید.
برای ویدیوهای محدود به سن یا خصوصی: Options > Video > Use cookies from browser.

## اجرا بدون نصب (برای توسعه)
```bash
sudo apt install python3-pyqt6 ffmpeg     # یا python3-pyqt5
python3 extension/build.py
python3 -m tondar
```

"""
====================================================================
 ربات قیمت طلا + شاخص نزدک (NASDAQ) برای کانال تلگرام
====================================================================

این ربات دو کار می‌کنه:

1) قیمت انس طلا:
   - هر چند ثانیه (GOLD_EDIT_INTERVAL) همون پیام قبلی رو ویرایش می‌کنه
     تا قیمت تقریباً زنده باشه، بدون اینکه کانالت پر از پیام بشه.
   - هر ۵ دقیقه (NEW_POST_INTERVAL) به‌جای ویرایش، یک پیام تازه می‌فرسته
     تا کانال یه سابقه/تاریخچه هم داشته باشه.

2) شاخص نزدک:
   - هر ۵ دقیقه (NASDAQ_INTERVAL) یک پیام جدید با آخرین مقدار شاخص
     نزدک (NASDAQ Composite) می‌فرسته.

این نسخه مقادیر حساس (توکن، آیدی کانال، کلید API) رو از environment variables
می‌خونه، نه از داخل خود فایل. این کار برای زمانی که کد رو رو گیت‌هاب/Render
می‌ذاری ضروریه، چون نباید توکن ربات و کلید API تو کد پابلیک دیده بشه.

موقع اجرا رو کامپیوتر خودت (تست محلی)، این متغیرها رو قبل از اجرا ست کن:
    Windows (CMD):
        set BOT_TOKEN=123456:ABC-DEF...
        set CHANNEL_ID=@your_channel
        set GOLDAPI_KEY=goldapi-xxxx
        python gold_nasdaq_bot.py

    Windows (PowerShell):
        $env:BOT_TOKEN="123456:ABC-DEF..."
        $env:CHANNEL_ID="@your_channel"
        $env:GOLDAPI_KEY="goldapi-xxxx"
        python gold_nasdaq_bot.py

    Mac/Linux:
        export BOT_TOKEN="123456:ABC-DEF..."
        export CHANNEL_ID="@your_channel"
        export GOLDAPI_KEY="goldapi-xxxx"
        python gold_nasdaq_bot.py

رو Render، این‌ها رو تو بخش Environment Variables توی داشبورد ست می‌کنی
(توضیحش تو راهنمای مکالمه هست) — نیازی به تغییر کد نیست.
====================================================================
"""

import os
import requests
import time
import logging
import threading
import yfinance as yf
from flask import Flask

# ==================== تنظیمات ====================
# این سه مقدار از environment variables خونده میشن (نه از تو کد)
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = os.environ.get("CHANNEL_ID")
GOLDAPI_KEY = os.environ.get("GOLDAPI_KEY")

# این‌ها رو می‌تونی مستقیم همینجا تغییر بدی (رازی نیستن، فرقی نمی‌کنه کجا باشن)
GOLD_EDIT_INTERVAL = 5      # هر چند ثانیه، پیام قیمت طلا رو ویرایش کنه
NEW_POST_INTERVAL = 300     # هر چند ثانیه (۳۰۰ = ۵ دقیقه)، به‌جای ویرایش، پیام تازه بفرسته
NASDAQ_INTERVAL = 300       # هر چند ثانیه (۳۰۰ = ۵ دقیقه)، شاخص نزدک رو بفرسته
# ===================================================

if not all([BOT_TOKEN, CHANNEL_ID, GOLDAPI_KEY]):
    raise SystemExit(
        "خطا: یکی از BOT_TOKEN, CHANNEL_ID, GOLDAPI_KEY ست نشده. "
        "این مقادیر رو باید به‌عنوان environment variable تعریف کنی "
        "(یا موقع اجرای محلی، یا تو تنظیمات Render)."
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
GOLDAPI_URL = "https://www.goldapi.io/api/XAU/USD"


# -------------------- توابع کمکی برای گرفتن قیمت‌ها --------------------

def get_gold_price():
    """قیمت لحظه‌ای انس طلا رو از GoldAPI می‌گیره."""
    headers = {"x-access-token": GOLDAPI_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.get(GOLDAPI_URL, headers=headers, timeout=5)
        resp.raise_for_status()
        return resp.json().get("price")
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در دریافت قیمت طلا: {e}")
        return None


def get_nasdaq_index():
    """آخرین مقدار شاخص نزدک (NASDAQ Composite) رو می‌گیره."""
    try:
        ticker = yf.Ticker("^IXIC")
        price = ticker.fast_info["last_price"]
        return price
    except Exception as e:
        logging.error(f"خطا در دریافت شاخص نزدک: {e}")
        return None


# -------------------- توابع کمکی برای ارتباط با تلگرام --------------------

def send_message(text: str):
    """یک پیام جدید می‌فرسته و آیدی پیام رو برمی‌گردونه (برای ویرایش بعدی)."""
    url = f"{API_BASE}/sendMessage"
    payload = {"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, data=payload, timeout=5)
        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
            logging.warning(f"محدودیت تلگرام؛ {retry_after} ثانیه صبر می‌کنیم")
            time.sleep(retry_after)
            return None
        resp.raise_for_status()
        return resp.json()["result"]["message_id"]
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در ارسال پیام: {e}")
        return None


def edit_message(message_id: int, text: str):
    """پیام قبلی رو با متن جدید ویرایش می‌کنه."""
    url = f"{API_BASE}/editMessageText"
    payload = {
        "chat_id": CHANNEL_ID,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, data=payload, timeout=5)
        if resp.status_code == 429:
            retry_after = resp.json().get("parameters", {}).get("retry_after", 5)
            logging.warning(f"محدودیت تلگرام؛ {retry_after} ثانیه صبر می‌کنیم")
            time.sleep(retry_after)
        elif not resp.ok:
            # اگه متن پیام دقیقاً همون قبلیه، تلگرام خطای "not modified" میده که مهم نیست
            if "message is not modified" not in resp.text:
                logging.error(f"خطا در ویرایش پیام ({resp.status_code}): {resp.text}")
    except requests.exceptions.RequestException as e:
        logging.error(f"خطا در ویرایش پیام: {e}")


# -------------------- سرور وب کوچیک (فقط برای اینکه Render بیدار نگهش داره) --------------------
# این سرور هیچ کار خاصی نمی‌کنه، فقط وقتی یه سرویس بیرونی (مثل UptimeRobot)
# بهش سر بزنه، جواب می‌ده و Render فکر می‌کنه سرویس زنده و فعاله، پس نمی‌خوابونتش.

web_app = Flask(__name__)


@web_app.route("/")
def health_check():
    return "ربات روشنه و داره کار می‌کنه ✅"


def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)


# -------------------- حلقه اصلی ربات --------------------

def main():
    logging.info("ربات شروع به کار کرد...")

    gold_message_id = None
    seconds_since_new_post = 0
    seconds_since_nasdaq = 0

    while True:
        # ---------- قیمت طلا ----------
        price = get_gold_price()
        if price is not None:
            text = f"🥇 نرخ انس طلا: <b>{price:,.2f}</b> دلار"

            need_new_post = (gold_message_id is None) or (seconds_since_new_post >= NEW_POST_INTERVAL)

            if need_new_post:
                new_id = send_message(text)
                if new_id is not None:
                    gold_message_id = new_id
                    seconds_since_new_post = 0
            else:
                edit_message(gold_message_id, text)

        # ---------- شاخص نزدک ----------
        if seconds_since_nasdaq >= NASDAQ_INTERVAL:
            nasdaq_price = get_nasdaq_index()
            if nasdaq_price is not None:
                nasdaq_text = f"📊 شاخص نزدک (NASDAQ): <b>{nasdaq_price:,.2f}</b>"
                send_message(nasdaq_text)
            seconds_since_nasdaq = 0

        # ---------- شمارنده‌ها رو جلو ببریم ----------
        time.sleep(GOLD_EDIT_INTERVAL)
        seconds_since_new_post += GOLD_EDIT_INTERVAL
        seconds_since_nasdaq += GOLD_EDIT_INTERVAL


if __name__ == "__main__":
    # حلقه ربات رو تو یه thread جدا اجرا می‌کنیم تا سرور وب هم بتونه همزمان کار کنه
    bot_thread = threading.Thread(target=main, daemon=True)
    bot_thread.start()

    # سرور وب رو تو thread اصلی اجرا می‌کنیم (Render بهش نیاز داره)
    run_web_server()

import os
import sqlite3
import subprocess
from datetime import datetime

import requests
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import os
import sys
import sqlite3
from datetime import datetime
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings

from main2 import scrape_product  # Your scraping logic

# ────────────────────────────────
# 🔁 Telegram Setup
# ────────────────────────────────
app = FastAPI()

BOT_TOKEN = "7746809844:AAHVMfdvWCTsZbelCFCDHVnZrBNJQKck09Y"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_message(chat_id, text, parse_mode=None):
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    requests.post(f"{API_URL}/sendMessage", json=payload)


# ────────────────────────────────
# 📦 Database Setup
# ────────────────────────────────

DB_PATH = os.path.abspath("selectors.db")
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
cursor = conn.cursor()

cursor.executescript('''
CREATE TABLE IF NOT EXISTS selectors (
    domain TEXT PRIMARY KEY,
    title_selector TEXT,
    price_selector TEXT
);
CREATE TABLE IF NOT EXISTS user_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    url TEXT,
    domain TEXT,
    title TEXT,
    price TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    remain_to_send_notification BOOLEAN DEFAULT 1,
    UNIQUE(chat_id, url)
);
''')
conn.commit()

# ────────────────────────────────
# 🕷️ Scrapy Runner (Safe via subprocess)
# ────────────────────────────────

def run_scrapy_with_notifications():
    try:
        print("🕷️ Launching Scrapy spider directly in Python...")

        # ✅ Setup path to the scrapy project directory
        base_dir = os.path.abspath(os.path.dirname(__file__))
        scraper_dir = os.path.join(base_dir, "product_scraper", "product_scraper")  # inner scrapy app dir
        os.chdir(scraper_dir)
        sys.path.append(scraper_dir)

        # ✅ Import spider dynamically
        from spiders.universal_spider import UniversalSpider

        # ✅ Run Scrapy Spider
        process = CrawlerProcess(get_project_settings())
        process.crawl(UniversalSpider)
        process.start()

        print("✅ Scrapy run finished, checking for notifications...")

        # ✅ Notification logic (your DB logic stays unchanged)
        db_conn = sqlite3.connect(DB_PATH)
        db_cursor = db_conn.cursor()
        db_cursor.execute("SELECT id, chat_id, title, price, url FROM user_urls WHERE remain_to_send_notification = 1")
        rows = db_cursor.fetchall()

        for row in rows:
            prod_id, chat_id, title, price, url = row
            message = (
                f"🔔 *Price Update!*\n\n"
                f"*{title}*\n"
                f"Price: {price}\n"
                f"[View Product]({url})"
            )
            send_message(chat_id, message)
            db_cursor.execute("UPDATE user_urls SET remain_to_send_notification = 0 WHERE id = ?", (prod_id,))
        
        db_conn.commit()
        db_conn.close()
        print("✅ Notifications sent.")

    except Exception as e:
        print(f"❌ Error running Scrapy or sending messages: {e}")# ────────────────────────────────
# ⏰ Schedule Background Job
# ────────────────────────────────

scheduler = BackgroundScheduler()
scheduler.add_job(run_scrapy_with_notifications, 'interval', minutes=5)  # or seconds=60 for testing
scheduler.start()
atexit.register(lambda: scheduler.shutdown())


# ────────────────────────────────
# 📬 Telegram Webhook Endpoint
# ────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return {"ok": True}

    # 🔄 Handle Commands
    if text.startswith("/delete"):
        try:
            product_id = text.replace("/delete", "").strip()
            cursor.execute("DELETE FROM user_urls WHERE id = ?", (product_id,))
            conn.commit()
            send_message(chat_id, "✅ Product deleted.")
        except Exception:
            send_message(chat_id, "❌ Invalid delete command.")
        return {"ok": True}

    elif text == "/list":
        cursor.execute("SELECT id, title, price, url FROM user_urls WHERE chat_id = ?", (chat_id,))
        rows = cursor.fetchall()

        if not rows:
            send_message(chat_id, "📭 No products being tracked.")
        else:
            msg = "📋 *Your Tracked Products:*\n\n"
            for idx, (id, title, price, url) in enumerate(rows, start=1):
                msg += f"{idx}. *{title}*\nPrice: {price}\n[View Product]({url})\nDelete: `/delete{id}`\n\n"
                msg += "-" * 40 + "\n"
            send_message(chat_id, msg, parse_mode="Markdown")
        return {"ok": True}

    elif not text.startswith("http"):
        send_message(chat_id, "❌ Please send a valid product URL.")
        return {"ok": True}

    # 🚫 Duplicate check
    cursor.execute("SELECT 1 FROM user_urls WHERE chat_id = ? AND url = ?", (chat_id, text))
    if cursor.fetchone():
        send_message(chat_id, "🔁 Product already being tracked.")
        return {"ok": True}

    # ➕ Process new product
    send_message(chat_id, "⏳ Processing product...")
    background.add_task(process_url_task, chat_id, text)

    return {"ok": True}


# ────────────────────────────────
# 🎯 Process Product URL and Save
# ────────────────────────────────

def process_url_task(chat_id: int, url: str):
    try:
        result = scrape_product(url)  # from main2.py

        cursor.execute('''
            INSERT INTO user_urls (chat_id, url, domain, title, price, remain_to_send_notification)
            VALUES (?, ?, ?, ?, ?, 1)
        ''', (chat_id, url, result["Domain"], result["Title"], result["Price"]))
        conn.commit()

        send_message(
            chat_id,
            f"✅ Product added:\n\n*{result['Title']}*\nPrice: {result['Price']}",
            parse_mode="Markdown"
        )

        cursor.execute('''
            UPDATE user_urls
            SET remain_to_send_notification = 0
            WHERE chat_id = ? AND url = ?
        ''', (chat_id, url))
        conn.commit()

    except Exception as e:
        send_message(chat_id, f"❌ Error while adding product: {e}")

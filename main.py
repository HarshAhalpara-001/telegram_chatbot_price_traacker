from fastapi import FastAPI, Request
import requests
import sqlite3
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import time
import re
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException
from google import genai
import sys
sys.stdout.reconfigure(encoding='utf-8')

# --- 0. FastAPI & Telegram Setup ---
app = FastAPI()
BOT_TOKEN = "7746809844:AAHVMfdvWCTsZbelCFCDHVnZrBNJQKck09Y"
API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

# --- 1. Gemini Setup ---
client = genai.Client(api_key='AIzaSyCyFGzYJdXUXkBpIGt46Gfv7TDrk646V4U')

# --- 2. SQLite DB ---
conn = sqlite3.connect("selectors.db", check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS selectors (
        domain TEXT PRIMARY KEY,
        title_selector TEXT,
        price_selector TEXT
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_urls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        url TEXT,
        domain TEXT,
        title TEXT,
        price TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(chat_id, url)
    )
''')
cursor.execute('''
    CREATE TABLE IF NOT EXISTS track_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_url_id INTEGER,  
    price TEXT,
    checked_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_url_id) REFERENCES user_urls(id) ON DELETE CASCADE
)
''')
conn.commit()

# --- 3. Webhook Route ---
@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    message = data.get("message")
    if not message:
        return {"ok": True}  # skip if it's not a valid text message

    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "").strip()

    if not chat_id or not text:
        return {"ok": True}
    if text.startswith("/delete_"):
        # Handle deletion of a specific product
        try:
            id = text.split("_")[1].strip()
            print(f"Deleting product with ID: {id} for chat_id: {chat_id}")
            cursor.execute("DELETE FROM user_urls WHERE id = ?", (id,))
            conn.commit()
            send_message(chat_id, {"message": "✅ Product deleted successfully."})
        except IndexError:
            send_message(chat_id, {"message": "❌ Please provide a valid URL to delete."})
        except Exception as e:
            send_message(chat_id, f"❌ Error: {e}")
        return {"ok": True}
    if text == "/list":
        # Fetch and send list of tracked products
        cursor.execute("SELECT id, title, price, url FROM user_urls WHERE chat_id = ?", (chat_id,))
        rows = cursor.fetchall()

        if not rows:
            send_message(chat_id, {"message": "📭 You're not tracking any products yet."})
        else:
            msg = "📋 *Your Tracked Products:*\n\n"
            for idx, (id,title, price, url) in enumerate(rows, start=1):
                msg += f"{idx}. *{title}*\nPrice: {price}\n[Link]({url})\nclick to delete /delete_{id}\n\n"
            send_message(chat_id,{"message": msg}, 
                        #  parse_mode="Markdown"
                         )
            return {"ok": True}
    print(f"Received message: {text} from chat_id: {chat_id}")
    if not text.startswith("http"):
        send_message(chat_id, {"message": "📦 Please send a valid product URL (Amazon/Zepto/Ajio)."})
        return {"ok": True}

    # --- Start scraping workflow ---
    try:
        cursor.execute("SELECT 1 FROM user_urls WHERE chat_id = ? AND url = ?", (chat_id, text))
        if cursor.fetchone():
            send_message(chat_id, {"message": "🔁 You've already added this product. We'll notify you if the price changes. /list to see the list."})
            return {"ok": True}
    except Exception as e:
        send_message(chat_id, {"message": f"❌ Error of timepass: {e}"})
    try:
        response = scrape_product(text)
        print(f"Scraped response: {response}")
        cursor.execute("INSERT INTO user_urls (chat_id, url, domain, title, price) VALUES (?, ?, ?, ?, ?)",
                       (chat_id, text, response['Domain'], response['Title'], response['Price']))
        conn.commit()
        send_message(chat_id, {"message": f"✅ Product added successfully:\n\n*Title:* {response['Title']}\n*Price:* {response['Price']}\n*Link:* {text}\n\n you can click on /list to see all your tracked products."})
    except Exception as e:
        send_message(chat_id, {"message": f"❌ Error: {e}"})
    return {"ok": True}

# --- 4. Scraper Function ---
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

def scrape_product(url: str) -> dict:
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")  # or False if you want browser UI
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/113.0 Safari/537.36")

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(10)
        driver.get(url)

        # Wait until body is fully loaded (or replace with smarter condition)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        final_url = driver.current_url  # Use after redirection
        html = driver.page_source
        soup = BeautifulSoup(html, "html.parser")

    except TimeoutException:
        raise Exception("Page load timed out.")
    except Exception as e:
        raise Exception(f"Failed to load page: {e}")
    finally:
        if driver:
            driver.quit()

    # --- Determine actual domain ---
    domain = urlparse(final_url).netloc

    # --- Check DB for selectors ---
    cursor.execute("SELECT title_selector, price_selector FROM selectors WHERE domain=?", (domain,))
    row = cursor.fetchone()

    if not row:
        # Use Gemini to extract selectors
        prompt = f"""
        You are given the HTML of a product page from an e-commerce website.
        Find and return ONLY the class names used to get the following:

        1. Product Title
        2. Product Price

        Only give class-based selectors (no ids). Example format:
        Title: class="product-title"
        Price: class="product-price"

        Only use class where the actual text is present (not parent divs).

        HTML:
        {html[:]}  # limit to avoid token overflow
        """
        gemini_response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        result = gemini_response.text

        title_match = re.search(r'Title:\s*class="([^"]+)"', result)
        price_match = re.search(r'Price:\s*class="([^"]+)"', result)

        title_selector = title_match.group(1) if title_match else None
        price_selector = price_match.group(1) if price_match else None

        if title_selector and price_selector:
            cursor.execute("INSERT OR REPLACE INTO selectors VALUES (?, ?, ?)", (domain, title_selector, price_selector))
            conn.commit()
        else:
            raise Exception("Gemini could not extract class selectors.")
    else:
        title_selector, price_selector = row

    # --- Extract title and price from soup ---
    def find_element(soup, selector):
        return soup.find(class_=selector)  # only class-based selection

    title_elem = find_element(soup, title_selector)
    price_elem = find_element(soup, price_selector)
    print(title_selector, price_selector)
    title = title_elem.get_text(strip=True) if title_elem else "❌ Title not found"
    price = price_elem.get_text(strip=True) if price_elem else "❌ Price not found"

    return {
        "Domain": domain,
        "Title": title,
        "Price": price
    }


# --- 5. Send Message ---
def send_message(chat_id, response, parse_mode=None):
    

    if isinstance(response, dict):
        text = response.get("message", "")
        parse_mode = response.get("parse_mode", parse_mode)
    else:
        text = response

    payload = {
        "chat_id": chat_id,
        "text": text,
        # "reply_markup": {
        #     "keyboard": [[{"text": "/list"}]],  # You can add more: [{"text": "/list"}, {"text": "/add"}]
        #     "resize_keyboard": True,
        #     "one_time_keyboard": False
        # }
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode

    url = f"{API_URL}/sendMessage"
    requests.post(url, json=payload)

'''
delete this comment this is to check if the code is working
This is a test comment to check if the code is working properly.
It should not affect the functionality of the code.
'''

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
from urllib.parse import urlparse
import sqlite3
import time
import re
from google import genai

# --- 1. Configure Gemini ---
client = genai.Client(api_key='AIzaSyCyFGzYJdXUXkBpIGt46Gfv7TDrk646V4U')

# --- 2. SQLite DB Setup ---
conn = sqlite3.connect("selectors.db")
cursor = conn.cursor()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS selectors (
        domain TEXT PRIMARY KEY,
        title_selector TEXT,
        price_selector TEXT
    )
''')
conn.commit()

# --- 3. Get User Input ---
url = input("Enter Product URL (Amazon or Zepto): ").strip()
domain = urlparse(url).netloc

# --- 4. Fetch HTML using Selenium ---
try:
    chrome_options = Options()
    chrome_options.add_argument("--headless=New")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/113.0 Safari/537.36")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(15)
    driver.get(url)
    time.sleep(5)  # wait for content to load

    html = driver.page_source
    driver.quit()
    soup = BeautifulSoup(html, "html.parser")
except TimeoutException:
    print("⚠️ Page load timed out.")
    exit()
except Exception as e:
    print(f"⚠️ Error fetching the URL via Selenium:\n{e}")
    exit()

# --- 5. Check DB for Selectors ---
cursor.execute("SELECT title_selector, price_selector FROM selectors WHERE domain=?", (domain,))
row = cursor.fetchone()

# --- 6. If Not in DB, Use Gemini to Find Selectors ---
if not row:
    prompt = f"""
    You are given the HTML of a product page from an e-commerce website.
    Find and return ONLY the class names used to get the following:

    1. Product Title
    2. Product Price

    Only give class-based selectors (no ids). Example format:
    Title: class="product-title"
    Price: class="product-price"

    Only use class where the actual text is present (not parent divs).

    Here is part of the HTML content:
    {html[:]}  # only give partial to avoid token limits
    """

    try:
        gemini_response = client.models.generate_content(
            model="gemini-2.5-flash", contents=prompt)
        result = gemini_response.text
        print("\n🤖 Gemini Response:\n", result)

        title_match = re.search(r'Title:\s*class="([^"]+)"', result)
        price_match = re.search(r'Price:\s*class="([^"]+)"', result)

        title_selector = title_match.group(1) if title_match else None
        price_selector = price_match.group(1) if price_match else None

        if title_selector and price_selector:
            # Save to DB
            cursor.execute("INSERT INTO selectors VALUES (?, ?, ?)", (domain, title_selector, price_selector))
            conn.commit()
        else:
            print("❌ Could not extract selectors from Gemini.")
            exit()

    except Exception as e:
        print("❌ Gemini API failed:", e)
        exit()
else:
    title_selector, price_selector = row

# --- 7. Parse Using Saved Selectors ---
def find_element_by_class_or_id(soup, selector):
    if soup.find(id=selector):
        return soup.find(id=selector)
    return soup.find(class_=selector)

title_element = find_element_by_class_or_id(soup, title_selector)
price_element = find_element_by_class_or_id(soup, price_selector)

print(f"\n🔎 Domain: {domain}")
print(title_element, "Title Selector:", title_selector)
print(price_element, "Price Selector:", price_selector)
print("Title:", title_element.get_text(strip=True) if title_element else "❌ Title not found")
print("Price:", price_element.get_text(strip=True) if price_element else "❌ Price not found")

conn.close()

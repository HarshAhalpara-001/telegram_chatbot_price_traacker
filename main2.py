import sqlite3
import re
import logging
import sys
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from google import genai

# Setup Gemini API
client = genai.Client(api_key="AIzaSyCyFGzYJdXUXkBpIGt46Gfv7TDrk646V4U")

# Configure logging and stdout
sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO)

# Connect to SQLite
conn = sqlite3.connect("selectors.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS selectors (
    domain TEXT PRIMARY KEY,
    title_selector TEXT,
    price_selector TEXT
)
""")
conn.commit()

def fetch_page_source(url: str) -> tuple[str, str]:
    """Fetch HTML content of the page using headless Chrome."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("user-agent=Mozilla/5.0")

    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(10)

    try:
        driver.get(url)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        final_url = driver.current_url
        html = driver.page_source
        return final_url, html
    except TimeoutException:
        raise Exception("❌ Timeout while loading the page.")
    finally:
        driver.quit()

def extract_selectors_with_llm(domain: str, html: str) -> tuple[str, str]:
    """Extract title and price class selectors from HTML using Gemini."""
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
{html[:50000]}
"""
    response = client.models.generate_content(model="gemini-2.0-flash",contents=prompt)
    result = response.text

    title_match = re.search(r'Title:\s*class="([^"]+)"', result)
    price_match = re.search(r'Price:\s*class="([^"]+)"', result)

    title_selector = title_match.group(1) if title_match else None
    price_selector = price_match.group(1) if price_match else None

    if not title_selector or not price_selector:
        raise Exception("❌ Could not extract selectors from Gemini.")

    cursor.execute("INSERT OR REPLACE INTO selectors VALUES (?, ?, ?)", (domain, title_selector, price_selector))
    conn.commit()

    return title_selector, price_selector

def scrape_product(url: str) -> dict:
    """Main function to scrape product title and price."""
    final_url, html = fetch_page_source(url)
    domain = urlparse(final_url).netloc
    soup = BeautifulSoup(html, "html.parser")

    cursor.execute("SELECT title_selector, price_selector FROM selectors WHERE domain=?", (domain,))
    row = cursor.fetchone()

    if not row:
        title_selector, price_selector = extract_selectors_with_llm(domain, html)
    else:
        title_selector, price_selector = row

    title = soup.find(class_=title_selector)
    price = soup.find(class_=price_selector)

    return {
        "Domain": domain,
        "Title": title.get_text(strip=True) if title else "❌ Title not found",
        "Price": price.get_text(strip=True) if price else "❌ Price not found"
    }

# # Example Usage
# if __name__ == "__main__":
#     test_url = "https://www.amazon.in/HARLEY-DAVIDSON-Motorcycle-440cc-booking-Ex-Showroom/dp/B0FDGY2KM1/?_encoding=UTF8&ref_=pd_hp_d_btf_ls_gwc_pc_en4_"
#     try:
#         result = scrape_product(test_url)
#         print("Scraped Result:")
#         for key, value in result.items():
#             print(f"{key}: {value}")
#     except Exception as e:
#         print("Error:", e)

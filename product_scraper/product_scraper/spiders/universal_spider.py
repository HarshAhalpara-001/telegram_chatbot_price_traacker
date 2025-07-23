import scrapy
import sqlite3
from urllib.parse import urlparse
import os
import re

class UniversalSpider(scrapy.Spider):
    name = "universal"
    DB_PATH = "C:/0_DATA/python/telegram_chat_bot/selectors.db"

    def start_requests(self):
        conn = sqlite3.connect(self.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, url FROM user_urls")
        urls = cursor.fetchall()
        conn.close()

        for product_id, url in urls:
            yield scrapy.Request(url=url, callback=self.parse, meta={"product_id": product_id})

    def get_selectors_from_db(self, domain):
        conn = sqlite3.connect(self.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT price_selector, title_selector FROM selectors WHERE domain = ?", (domain,))
        result = cursor.fetchone()
        conn.close()
        if result:
            return {
                "price_selector": result[0],
                "title_selector": result[1]
            }
        return None

    def update_price_in_db(self, product_id, new_price):
        try:
            conn = sqlite3.connect(self.DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT price FROM user_urls WHERE id = ?", (product_id,))
            row = cursor.fetchone()

            if row:
                current_price = row[0]
                print('-' * 50)
                print(f"🟡 Product ID {product_id}: Current price: {current_price} | New price: {new_price}")
                if current_price != new_price:
                    cursor.execute("""
                        UPDATE user_urls
                        SET price = ?, remain_to_send_notification = 1, timestamp = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (new_price, int(product_id)))
                    conn.commit()
                    self.logger.info(f"🟢 Price CHANGED. Updated DB for product ID {product_id}")
                else:
                    self.logger.info(f"✅ Price unchanged for product ID {product_id}")
            conn.close()
        except Exception as e:
            self.logger.error(f"❌ Failed to update DB for product ID {product_id}: {e}")

    def normalize_selector(self, selector):
        # Convert class names to valid CSS selectors with proper escaping
        class_parts = selector.strip().split()
        escaped_parts = [re.sub(r'([\[\]#:().])', r'\\\1', cls) for cls in class_parts]
        return "." + ".".join(escaped_parts)

    def parse(self, response):
        domain = urlparse(response.url).netloc
        product_id = response.meta["product_id"]
        selectors = self.get_selectors_from_db(domain)

        self.logger.info(f"🔍 Parsing product ID {product_id} - {response.url} (Domain: {domain})")

        if not selectors:
            self.logger.warning(f"❌ No CSS selectors found for domain: {domain} (product_id: {product_id})")
            return

        price_css = self.normalize_selector(selectors["price_selector"])
        title_css = self.normalize_selector(selectors["title_selector"])

        price = response.css(f"{price_css}::text").get()
        title = response.css(f"{title_css}::text").get()

        if price and title:
            price = price.strip()
            title = title.strip()
            self.update_price_in_db(product_id, price)
            self.logger.info(f"✅ Product ID {product_id}: Title: {title} | Price: {price}")
        else:
            self.logger.warning(f"⚠️ Extraction failed for product ID {product_id} ({domain})")

import os
import sys
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
# 👇 Set working directory to the Scrapy project
scrapy_project_dir = os.path.join(os.getcwd(), "product_scraper", "product_scraper")
os.chdir(scrapy_project_dir)
# 👇 Add scrapy project to sys.path so imports work
sys.path.append(scrapy_project_dir)
# 👇 Now import the spider
from spiders.universal_spider import UniversalSpider

def run_universal_spider():
    process = CrawlerProcess(get_project_settings())
    process.crawl(UniversalSpider)
    process.start()

if __name__ == "__main__":
    run_universal_spider()

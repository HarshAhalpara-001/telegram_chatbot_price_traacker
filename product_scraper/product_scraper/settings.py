BOT_NAME = 'product_scraper'

SPIDER_MODULES = ['product_scraper.spiders']
NEWSPIDER_MODULE = 'product_scraper.spiders'

ROBOTSTXT_OBEY = False

DOWNLOADER_MIDDLEWARES = {
    'scrapy_user_agents.middlewares.RandomUserAgentMiddleware': 400,
}

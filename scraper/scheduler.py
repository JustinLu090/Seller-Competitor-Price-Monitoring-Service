import logging
import os
import time

import psycopg2
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

from kafka_producer import send_price_event
from shopee_spider import fetch_product

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
SCRAPE_INTERVAL_MINUTES = int(os.getenv("SCRAPE_INTERVAL_MINUTES", "30"))


def get_active_products() -> list[dict]:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.shopee_item_id, p.shopee_shop_id, p.name
                FROM products p
                WHERE p.active = TRUE
                """
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def scrape_all():
    logger.info("Starting scheduled scrape run")
    try:
        products = get_active_products()
    except Exception as e:
        logger.error("Failed to fetch products from DB: %s", e)
        return

    logger.info("Found %d active products to scrape", len(products))
    for product in products:
        result = fetch_product(product["shopee_shop_id"], product["shopee_item_id"])
        if result:
            send_price_event(product["id"], result)
        # Polite delay between requests
        time.sleep(1.5)

    logger.info("Scrape run complete")


def main():
    # Wait for other services to be ready
    time.sleep(15)

    # Run once immediately on startup
    scrape_all()

    scheduler = BlockingScheduler()
    scheduler.add_job(scrape_all, "interval", minutes=SCRAPE_INTERVAL_MINUTES)
    logger.info("Scheduler started — interval: %d minutes", SCRAPE_INTERVAL_MINUTES)
    scheduler.start()


if __name__ == "__main__":
    main()

import os
import re
import time
import requests
import logging

logger = logging.getLogger(__name__)

SHOPEE_ITEM_API = "https://shopee.tw/api/v4/item/get"

_cookie = os.getenv("SHOPEE_COOKIE", "")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://shopee.tw/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "sec-ch-ua": '"Google Chrome";v="120", "Chromium";v="120"',
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    **({"Cookie": _cookie} if _cookie else {}),
}


def parse_shopee_url(url: str) -> tuple[int, int]:
    """Extract (shop_id, item_id) from a Shopee product URL."""
    m = re.search(r"-i\.(\d+)\.(\d+)", url)
    if not m:
        raise ValueError(f"Cannot parse Shopee URL: {url}")
    return int(m.group(1)), int(m.group(2))


def fetch_product(shop_id: int, item_id: int, retries: int = 3) -> dict | None:
    """Fetch product info from Shopee public API. Returns None on failure."""
    params = {"itemid": item_id, "shopid": shop_id}

    for attempt in range(retries):
        try:
            resp = requests.get(
                SHOPEE_ITEM_API,
                params=params,
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()

            item = data.get("data") or data.get("item")
            if not item:
                logger.warning("No item data for shop=%s item=%s", shop_id, item_id)
                return None

            price_raw = item.get("price_min") or item.get("price", 0)
            return {
                "name": item.get("name", ""),
                "price": price_raw / 100000,  # Shopee stores price * 100000
                "stock": item.get("stock", 0),
                "sold_count": item.get("historical_sold", 0),
                "rating": item.get("item_rating", {}).get("rating_star", 0),
                "shop_id": shop_id,
                "item_id": item_id,
            }

        except requests.exceptions.RequestException as e:
            logger.warning("Attempt %d failed for item %s: %s", attempt + 1, item_id, e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    return None

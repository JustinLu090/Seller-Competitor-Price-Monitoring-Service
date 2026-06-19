import re
import time
import requests
import logging

logger = logging.getLogger(__name__)

YAHOO_PRODUCT_URL = "https://tw.buy.yahoo.com/gdsale/gdsale.asp"
YAHOO_SEARCH_URL = "https://tw.buy.yahoo.com/search/product"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8",
    "Referer": "https://tw.buy.yahoo.com/",
}

# Known brand names to skip when building search keywords
_BRAND_PREFIXES = {
    "esense", "apple", "samsung", "sony", "asus", "acer", "hp", "dell",
    "lenovo", "lg", "philips", "logitech", "anker", "ugreen", "belkin",
    "buffalo", "wd", "seagate", "kingston", "corsair", "msi", "gigabyte",
}

# Material/spec adjectives that are too specific for competitor search
_MATERIAL_WORDS = {"鋁合金", "不鏽鋼", "矽膠", "尼龍", "金屬", "塑膠", "合金", "皮革", "碳纖維"}


def parse_yahoo_url(url: str) -> int:
    """Extract gdid from a Yahoo Shopping product URL."""
    m = re.search(r"gdid=(\d+)", url)
    if not m:
        raise ValueError(f"Cannot parse Yahoo Shopping URL: {url}")
    return int(m.group(1))


def _extract_keyword(name: str) -> str:
    """
    Extract a competitor-search keyword from a product name.
    Skips brand tokens (both English and the Chinese brand that follows),
    then picks product-type acronyms + Chinese category terms.
    """
    tokens = name.split()

    # Skip leading brand token(s)
    skip = 0
    if tokens:
        first = tokens[0].lower().rstrip(".,")
        if first in _BRAND_PREFIXES:
            skip = 1
            # Also skip the immediately following Chinese brand name (2–4 Chinese chars)
            if len(tokens) > 1 and re.fullmatch(r"[一-鿿]{2,4}", tokens[1]):
                skip = 2

    remaining = tokens[skip:]

    type_abbrevs: list[str] = []
    category_words: list[str] = []

    for t in remaining:
        clean = t.strip(".,()[]")
        # Match product-type acronyms (possibly followed by version: USB3.2 → USB)
        m = re.match(r"^(USB|HUB|SSD|RAM|HDMI|SATA|NVMe|Type-C)", clean, re.I)
        if m:
            abbrev = m.group(0).upper().replace("TYPE-C", "Type-C")
            if abbrev not in type_abbrevs:
                type_abbrevs.append(abbrev)
        # Chinese category words: ≥2 chars, no digits, not a material/spec descriptor
        elif re.search(r"[一-鿿]{2,}", clean) and not re.search(r"\d", clean) and clean not in _MATERIAL_WORDS:
            category_words.append(clean)

        if len(type_abbrevs) >= 2 and len(category_words) >= 2:
            break

    combined = type_abbrevs[:2] + category_words[:2]
    keyword = " ".join(combined[:4]).strip()
    if not keyword:
        keyword = " ".join(remaining[:3])
    return keyword


def search_competitor_gdids(keyword: str, exclude_gdid: int, limit: int = 5) -> list[int]:
    """Search Yahoo Shopping and return up to `limit` competitor gdids."""
    try:
        resp = requests.get(
            YAHOO_SEARCH_URL,
            params={"p": keyword, "first": 1},
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.warning("Search failed for keyword=%s: %s", keyword, e)
        return []

    all_ids = re.findall(r"gdid=(\d+)", resp.text)
    seen: set[str] = set()
    unique: list[int] = []
    for raw_id in all_ids:
        if raw_id in seen or int(raw_id) == exclude_gdid:
            continue
        seen.add(raw_id)
        unique.append(int(raw_id))
        if len(unique) >= limit:
            break
    return unique


def fetch_product(gdid: int, retries: int = 3) -> dict | None:
    """Fetch product info from a Yahoo Shopping product page."""
    for attempt in range(retries):
        try:
            resp = requests.get(
                YAHOO_PRODUCT_URL,
                params={"gdid": gdid},
                headers=HEADERS,
                timeout=8,
            )
            resp.raise_for_status()
            html = resp.text

            title_m = re.search(r"<title>(.*?)\s*[|｜]", html, re.DOTALL)
            name = title_m.group(1).strip() if title_m else f"商品 {gdid}"

            price_m = re.search(
                r'"(?:price|salePrice|Price|SalePrice)"\s*:\s*"?(\d{2,7})"?', html
            )
            if not price_m:
                logger.warning("No price found for gdid=%s", gdid)
                return None

            price = float(price_m.group(1))
            if price <= 0:
                return None

            stock_m = re.search(r'"(?:stock|Stock)"\s*:\s*(\d+)', html)
            stock = int(stock_m.group(1)) if stock_m else 0

            return {
                "name": name,
                "price": price,
                "stock": stock,
                "sold_count": 0,
                "rating": 0.0,
                "gdid": gdid,
            }

        except requests.exceptions.RequestException as e:
            logger.warning("Attempt %d failed for gdid %s: %s", attempt + 1, gdid, e)
            if attempt < retries - 1:
                time.sleep(2 ** attempt)

    return None

"""
App Store 分析 + 競品定價 Benchmark：

1. 蝦皮購物主 App（ID: 959841107）評論爬取
   → 搜尋含「賣家」「比價」「競品」「通知」的評論，量化需求
2. 爬取現有競品工具（Prisync / Price2Spy）的定價頁面
   → 建立 WTP（願付金額）的市場基準
"""
import csv
import re
import time
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).parent / "output"

SHOPEE_APP_ID = 959841107  # 蝦皮購物（台灣主 App，78 萬評論）
ITUNES_RSS = "https://itunes.apple.com/tw/rss/customerreviews/page={page}/id={app_id}/sortby=mostrecent/json"

DEMAND_KEYWORDS = [
    "賣家", "比價", "競品", "通知", "提醒", "監控",
    "price", "alert", "seller", "notify", "competitor",
]

COMPETITOR_TOOLS = [
    {
        "name": "Prisync",
        "url": "https://prisync.com/pricing/",
        "price_pattern": r"(\d+)\s*USD\s*/?\s*(?:per\s*)?month|start.{0,30}(\d+)\s*USD",
        "currency": "USD",
    },
    {
        "name": "Price2Spy",
        "url": "https://www.price2spy.com/en/pricing/",
        "price_pattern": r"\$\s*(\d+(?:\.\d+)?)\s*/?\s*(?:month|mo\b)",
        "currency": "USD",
    },
]


def fetch_app_reviews(app_id: int, max_pages: int = 10) -> list[dict]:
    """抓取 App Store 評論（只有 page 2 回傳資料，其餘頁面為空）。"""
    headers = {"User-Agent": "iTunes/12.0"}
    reviews = []

    for page in range(1, max_pages + 1):
        url = ITUNES_RSS.format(page=page, app_id=app_id)
        resp = requests.get(url, headers=headers, timeout=10)
        if not resp.ok:
            continue

        entries = resp.json().get("feed", {}).get("entry", [])
        if not entries:
            continue

        # 第一個 entry 是 App 資訊，跳過
        for entry in entries:
            if isinstance(entry.get("im:name"), dict):
                continue
            reviews.append({
                "title": entry.get("title", {}).get("label", ""),
                "content": entry.get("content", {}).get("label", ""),
                "rating": entry.get("im:rating", {}).get("label", ""),
                "date": entry.get("updated", {}).get("label", "")[:10],
            })
        time.sleep(0.5)

    return reviews


def analyze_demand(reviews: list[dict]) -> list[dict]:
    matched = []
    for r in reviews:
        text = (r["title"] + " " + r["content"]).lower()
        hits = [kw for kw in DEMAND_KEYWORDS if kw in text]
        if hits:
            matched.append({**r, "matched_keywords": ", ".join(hits)})
    return matched


def scrape_competitor_pricing() -> list[dict]:
    """爬取競品工具定價頁面，建立 WTP 基準。"""
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for tool in COMPETITOR_TOOLS:
        try:
            resp = requests.get(tool["url"], headers=headers, timeout=10)
            # 找定價：從頁面文字提取
            text = resp.text
            prices = re.findall(tool["price_pattern"], resp.text, re.IGNORECASE)
            # 展平 tuple 結果，取非空值
            flat_prices = []
            for p in prices:
                if isinstance(p, tuple):
                    flat_prices.extend(v for v in p if v)
                else:
                    flat_prices.append(p)

            numeric_prices = sorted(set(float(p) for p in flat_prices if p))
            min_price = numeric_prices[0] if numeric_prices else None

            # 額外搜尋「start from」或 plan descriptions
            plan_snippet = ""
            snippet_match = re.search(
                r"(?:start|plans?.{0,20}from).{0,60}(?:USD|\$)\s*(\d+)", text, re.IGNORECASE
            )
            if snippet_match:
                plan_snippet = snippet_match.group(0)[:100].strip()

            results.append({
                "tool": tool["name"],
                "url": tool["url"],
                "currency": tool["currency"],
                "min_price": min_price,
                "all_prices_found": numeric_prices[:5],
                "snippet": plan_snippet,
                "usd_to_twd": 32,  # approximate exchange rate
                "min_price_twd": round(min_price * 32) if min_price else None,
            })
            print(f"  {tool['name']}: min ${min_price} {tool['currency']} (~NT${round(min_price * 32) if min_price else 'N/A'})")

        except Exception as e:
            print(f"  [WARNING] {tool['name']} 定價頁面抓取失敗：{e}")
            results.append({"tool": tool["name"], "error": str(e)})

        time.sleep(1)

    return results


def run(max_pages: int = 10) -> dict:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 1. App Store 評論
    print(f"[AppStore] 抓取蝦皮購物 App 評論 (ID: {SHOPEE_APP_ID})...")
    reviews = fetch_app_reviews(SHOPEE_APP_ID, max_pages)
    matched = analyze_demand(reviews)

    rating_dist = {}
    for r in reviews:
        rating_dist[r["rating"]] = rating_dist.get(r["rating"], 0) + 1

    # 儲存
    all_csv = OUTPUT_DIR / "appstore_all_reviews.csv"
    with open(all_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "rating", "title", "content"])
        writer.writeheader()
        writer.writerows(reviews)

    matched_csv = OUTPUT_DIR / "appstore_demand_reviews.csv"
    with open(matched_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "rating", "title", "content", "matched_keywords"])
        writer.writeheader()
        writer.writerows(matched)

    demand_pct = round(len(matched) / len(reviews) * 100, 1) if reviews else 0
    print(f"  總評論：{len(reviews)} 筆，含需求關鍵字：{len(matched)} 筆（{demand_pct}%）")
    for r in matched[:5]:
        print(f"  ★{r['rating']} [{r['matched_keywords']}] {r['title'][:50]}")

    # 2. 競品定價 Benchmark
    print("\n[Competitor Pricing] 抓取競品工具定價...")
    competitor_data = scrape_competitor_pricing()

    comp_csv = OUTPUT_DIR / "competitor_pricing.csv"
    with open(comp_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["tool", "currency", "min_price", "min_price_twd", "snippet", "url"])
        writer.writeheader()
        for c in competitor_data:
            if "error" not in c:
                writer.writerow({k: c.get(k, "") for k in writer.fieldnames})

    print(f"\n[AppStore + Competitor] 完成")

    return {
        "app_id": SHOPEE_APP_ID,
        "total_reviews": len(reviews),
        "demand_matched": len(matched),
        "demand_rate_pct": demand_pct,
        "rating_distribution": rating_dist,
        "all_csv": str(all_csv),
        "matched_csv": str(matched_csv),
        "competitor_pricing": competitor_data,
        "competitor_csv": str(comp_csv),
    }


if __name__ == "__main__":
    run()

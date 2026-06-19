"""
台灣電商市場規模分析：
透過 App Store 評分數量 + Google News 媒體覆蓋量
量化台灣蝦皮賣家的市場基礎，作為系統商業潛力的佐證。
"""
import csv
import re
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
import requests

for _font in ["PingFang TC", "Heiti TC", "STHeiti", "Arial Unicode MS"]:
    if any(f.name == _font for f in _fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _font
        break

OUTPUT_DIR = Path(__file__).parent / "output"

APPS_TO_ANALYZE = [
    {"name": "蝦皮購物 (Buyer)", "app_id": 959841107, "role": "buyer"},
    {"name": "蝦皮賣家中心 (Seller)", "app_id": 6749287561, "role": "seller"},
]

NEWS_TOPICS = [
    ("蝦皮賣家 利潤", "賣家利潤相關"),
    ("蝦皮賣家 降價", "降價競爭相關"),
    ("電商 賣家工具 台灣", "賣家工具需求"),
    ("shopee taiwan seller", "英文媒體報導"),
]

ITUNES_LOOKUP = "https://itunes.apple.com/lookup?id={app_id}&country=tw"
NEWS_RSS = "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"


def fetch_app_metadata(app_id: int) -> dict:
    """從 iTunes Lookup API 取得 App 的評分數量（不需登入）。"""
    try:
        resp = requests.get(
            ITUNES_LOOKUP.format(app_id=app_id),
            headers={"User-Agent": "iTunes/12.0"},
            timeout=10,
        )
        results = resp.json().get("results", [])
        if results:
            r = results[0]
            return {
                "app_id": app_id,
                "name": r.get("trackName", ""),
                "rating": r.get("averageUserRating", 0),
                "rating_count": r.get("userRatingCount", 0),
                "rating_count_current": r.get("userRatingCountForCurrentVersion", 0),
                "version": r.get("version", ""),
                "genre": r.get("primaryGenreName", ""),
            }
    except Exception as e:
        print(f"  [WARNING] iTunes Lookup 失敗 (id={app_id}): {e}")
    return {}


def fetch_news_count(query: str, label: str) -> dict:
    """抓取 Google News RSS 的新聞數量。"""
    url = NEWS_RSS.format(q=requests.utils.quote(query))
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        titles = re.findall(r"<title>(.+?)</title>", resp.text)
        # 過濾掉 feed title 和 Google 相關
        real_titles = [t for t in titles if "Google" not in t and len(t) > 5]
        return {
            "query": query,
            "label": label,
            "article_count": len(real_titles),
            "sample_titles": real_titles[:5],
        }
    except Exception as e:
        print(f"  [WARNING] Google News 失敗 ({query}): {e}")
        return {"query": query, "label": label, "article_count": 0}


def plot_market_overview(app_data: list[dict], news_data: list[dict], out_path: Path):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # App 評分數量（市場規模代理指標）
    names = [d.get("name", f"App {d.get('app_id', '')}") for d in app_data if d]
    counts = [d.get("rating_count", 0) for d in app_data if d]
    if names and counts:
        bars = ax1.barh(names, counts, color=["#2196F3", "#FF5722"])
        ax1.set_xlabel("Number of App Store Ratings")
        ax1.set_title("Taiwan Shopee App Market Scale\n(Ratings = Proxy for User Base)")
        ax1.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x/1000:.0f}K"))
        for bar, count in zip(bars, counts):
            ax1.text(bar.get_width() * 0.05, bar.get_y() + bar.get_height() / 2,
                     f"{count:,}", va="center", fontsize=9, color="white", fontweight="bold")

    # Google News 文章數量（媒體覆蓋率）
    if news_data:
        labels = [d["label"] for d in news_data]
        article_counts = [d["article_count"] for d in news_data]
        ax2.bar(range(len(labels)), article_counts, color="#4CAF50")
        ax2.set_xticks(range(len(labels)))
        ax2.set_xticklabels(labels, rotation=15, ha="right", fontsize=8)
        ax2.set_ylabel("News Articles (Google News RSS)")
        ax2.set_title("Media Coverage of Taiwan E-commerce Sellers\n(Google News)")
        ax2.grid(axis="y", alpha=0.3)

    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  市場概覽圖已儲存：{out_path}")


def run() -> dict:
    OUTPUT_DIR.mkdir(exist_ok=True)

    # 1. App Store 元數據（評分數量）
    print("[Market] 取得 App Store 評分統計...")
    app_data = []
    for app in APPS_TO_ANALYZE:
        meta = fetch_app_metadata(app["app_id"])
        if meta:
            meta["role"] = app["role"]
            app_data.append(meta)
            print(
                f"  {meta.get('name', app['name'])}: "
                f"{meta.get('rating_count', 0):,} 評分, "
                f"平均 {meta.get('rating', 0):.1f} 星"
            )
        time.sleep(0.5)

    # 2. Google News 文章數量
    print("\n[Market] 計算 Google News 媒體覆蓋量...")
    news_data = []
    for query, label in NEWS_TOPICS:
        result = fetch_news_count(query, label)
        news_data.append(result)
        print(f'  "{label}": {result["article_count"]} 篇新聞')
        if result.get("sample_titles"):
            for t in result["sample_titles"][:2]:
                print(f"    · {t[:60]}")
        time.sleep(1)

    # 儲存 CSV
    app_csv = OUTPUT_DIR / "appstore_market_stats.csv"
    if app_data:
        with open(app_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "app_id", "role", "rating", "rating_count", "version"])
            writer.writeheader()
            for d in app_data:
                writer.writerow({k: d.get(k, "") for k in writer.fieldnames})

    news_csv = OUTPUT_DIR / "google_news_market.csv"
    with open(news_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["label", "query", "article_count"])
        writer.writeheader()
        for d in news_data:
            writer.writerow({k: d.get(k, "") for k in writer.fieldnames})

    # 繪圖
    chart_path = OUTPUT_DIR / "market_overview_chart.png"
    plot_market_overview(app_data, news_data, chart_path)

    total_buyer_ratings = sum(d.get("rating_count", 0) for d in app_data if d.get("role") == "buyer")
    total_news = sum(d.get("article_count", 0) for d in news_data)

    print(f"\n[Market] 完成")
    print(f"  蝦皮購物 App 台灣評分數：{total_buyer_ratings:,}（代表大量活躍使用者）")
    print(f"  相關 Google 新聞總計：{total_news} 篇")

    return {
        "app_data": app_data,
        "news_data": news_data,
        "total_buyer_ratings": total_buyer_ratings,
        "total_news_coverage": total_news,
        "app_csv": str(app_csv),
        "news_csv": str(news_csv),
        "chart_path": str(chart_path),
    }


if __name__ == "__main__":
    run()

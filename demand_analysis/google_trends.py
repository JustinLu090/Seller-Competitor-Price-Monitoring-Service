"""
Google Trends + Google News RSS 分析：
1. 用 pytrends 抓搜尋趨勢（英文關鍵字避免 rate limit）
2. 用 Google News RSS 抓蝦皮賣家相關新聞標題，量化媒體關注度
"""
import csv
import re
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as _fm
import pandas as pd

for _font in ["PingFang TC", "Heiti TC", "STHeiti", "Arial Unicode MS"]:
    if any(f.name == _font for f in _fm.fontManager.ttflist):
        matplotlib.rcParams["font.family"] = _font
        break
import requests
from pytrends.request import TrendReq

OUTPUT_DIR = Path(__file__).parent / "output"

# 英文關鍵字（中文關鍵字容易觸發 429）
TRENDS_KEYWORDS = [
    "shopee seller",
    "price monitoring",
    "competitor price",
]

NEWS_QUERIES = [
    "蝦皮賣家",
    "蝦皮 競品",
    "電商賣家工具",
]

NEWS_RSS_BASE = (
    "https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
)


def fetch_trends(keywords: list[str], timeframe: str = "today 12-m", geo: str = "TW") -> pd.DataFrame | None:
    try:
        pytrends = TrendReq(hl="zh-TW", tz=480, timeout=(10, 25))
        pytrends.build_payload(keywords, timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
        if "isPartial" in df.columns:
            df = df.drop(columns=["isPartial"])
        return df
    except Exception as e:
        print(f"  [WARNING] pytrends 失敗：{e}")
        return None


def fetch_news(query: str) -> list[dict]:
    """從 Google News RSS 抓新聞標題。"""
    url = NEWS_RSS_BASE.format(q=requests.utils.quote(query))
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        titles = re.findall(r"<title>(.+?)</title>", resp.text)
        # 第一個是 feed title，跳過
        return [{"query": query, "title": t} for t in titles[1:] if t and "Google" not in t]
    except Exception as e:
        print(f"  [WARNING] Google News 失敗：{e}")
        return []


def plot_trends(df: pd.DataFrame, out_path: Path):
    fig, ax = plt.subplots(figsize=(10, 4))
    for col in df.columns:
        ax.plot(df.index, df[col], label=col, linewidth=2)
    ax.set_title("Google Search Trends - TW (12 months)", fontsize=13)
    ax.set_ylabel("Relative Interest (0-100)")
    ax.set_xlabel("Month")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  趨勢圖已儲存：{out_path}")


def run() -> dict:
    OUTPUT_DIR.mkdir(exist_ok=True)
    result = {}

    # 1. Google Trends
    print("[Google Trends] 抓取搜尋趨勢...")
    df = fetch_trends(TRENDS_KEYWORDS)
    if df is not None and not df.empty:
        csv_path = OUTPUT_DIR / "google_trends.csv"
        df.to_csv(csv_path, encoding="utf-8")
        chart_path = OUTPUT_DIR / "google_trends_chart.png"
        plot_trends(df, chart_path)

        stats = {}
        for col in df.columns:
            s = df[col].dropna()
            if len(s) >= 3:
                stats[col] = {
                    "avg_12m": round(float(s.mean()), 1),
                    "avg_last3m": round(float(s.iloc[-3:].mean()), 1),
                    "peak": int(s.max()),
                    "trend": "rising" if s.iloc[-3:].mean() > s.iloc[:3].mean() else "stable/falling",
                }
        result["trends_stats"] = stats
        result["trends_csv"] = str(csv_path)
        result["trends_chart"] = str(chart_path)
        print(f"  完成：{len(df)} 週資料，關鍵字：{list(df.columns)}")
        for kw, s in stats.items():
            print(f"  {kw}: avg={s['avg_12m']}, trend={s['trend']}")
    else:
        print("  Google Trends 無資料（可能限流），僅使用 Google News")

    # 2. Google News RSS
    print("\n[Google News] 抓取台灣蝦皮賣家相關新聞...")
    all_news = []
    for query in NEWS_QUERIES:
        articles = fetch_news(query)
        all_news.extend(articles)
        print(f'  "{query}": {len(articles)} 則新聞')
        time.sleep(1)

    # 去重
    seen_titles = set()
    unique_news = []
    for a in all_news:
        if a["title"] not in seen_titles:
            seen_titles.add(a["title"])
            unique_news.append(a)

    news_csv = OUTPUT_DIR / "google_news.csv"
    with open(news_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["query", "title"])
        writer.writeheader()
        writer.writerows(unique_news)

    result["news_count"] = len(unique_news)
    result["news_csv"] = str(news_csv)
    result["news_sample"] = [a["title"] for a in unique_news[:10]]

    print(f"\n[Google Trends + News] 完成")
    print(f"  新聞去重後共 {len(unique_news)} 則")
    for t in unique_news[:5]:
        print(f"  · {t['title'][:70]}")

    return result


if __name__ == "__main__":
    run()

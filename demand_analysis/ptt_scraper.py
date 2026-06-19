"""
PTT 電商版面關鍵字搜尋：
使用 PTT 的 /search 功能在 e-shopping、BuyTogether 板搜尋
「降價」「蝦皮賣家」「比價」「賣家工具」等關鍵字，
量化公開討論中對競品定價監控需求的討論頻次。
"""
import csv
import re
import time
from datetime import datetime
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).parent / "output"

BOARDS = ["e-shopping", "BuyTogether"]

SEARCH_KEYWORDS = [
    "蝦皮賣家",
    "比價",
    "降價通知",
    "賣家工具",
    "比價軟體",
    "降價",
]

# 標題中含下列詞，代表有競品定價需求
DEMAND_SIGNALS = [
    "比價", "比價軟體", "監控", "降價通知", "賣家工具", "競品",
    "price alert", "蝦皮賣家", "賣家",
]

BASE_URL = "https://www.ptt.cc"
SESSION = requests.Session()
SESSION.cookies.set("over18", "1", domain="www.ptt.cc")
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


def search_board(board: str, keyword: str) -> list[dict]:
    """使用 PTT 的 search 功能搜尋特定關鍵字。"""
    resp = SESSION.get(
        f"{BASE_URL}/bbs/{board}/search",
        params={"q": keyword},
        timeout=10,
    )
    if resp.status_code != 200:
        return []

    articles = re.findall(
        r'class="title">\s*<a href="(/bbs/[^"]+)">([^<]+)</a>',
        resp.text,
    )
    return [
        {
            "board": board,
            "keyword": keyword,
            "url": f"{BASE_URL}{url}",
            "title": title.strip(),
        }
        for url, title in articles
    ]


def tag_demand_signal(title: str) -> bool:
    """判斷這篇文章是否暗示對比價/監控工具的需求。"""
    title_lower = title.lower()
    return any(sig in title_lower for sig in DEMAND_SIGNALS)


def run() -> dict:
    OUTPUT_DIR.mkdir(exist_ok=True)

    seen = set()
    all_results = []

    for board in BOARDS:
        for keyword in SEARCH_KEYWORDS:
            results = search_board(board, keyword)
            for r in results:
                key = r["url"]
                if key not in seen:
                    seen.add(key)
                    r["demand_signal"] = tag_demand_signal(r["title"])
                    r["scraped_at"] = datetime.now().isoformat()
                    all_results.append(r)

            count = len([r for r in results if r["url"] not in seen - {r["url"]}])
            print(f'  [{board}] "{keyword}": {len(results)} 筆')
            time.sleep(0.6)

    demand_articles = [r for r in all_results if r["demand_signal"]]

    # 儲存 CSV
    out_path = OUTPUT_DIR / "ptt_results.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["board", "keyword", "title", "url", "demand_signal", "scraped_at"]
        )
        writer.writeheader()
        writer.writerows(all_results)

    print(f"\n[PTT] 完成")
    print(f"  去重後共找到 {len(all_results)} 篇相關文章")
    print(f"  其中含「比價/監控工具需求」明確信號：{len(demand_articles)} 篇")
    for r in demand_articles[:5]:
        print(f"    ★ [{r['board']}] {r['title']}")

    board_summary = {}
    for r in all_results:
        board_summary[r["board"]] = board_summary.get(r["board"], 0) + 1

    return {
        "total_articles": len(all_results),
        "demand_signal_articles": len(demand_articles),
        "by_board": board_summary,
        "notable_titles": [r["title"] for r in demand_articles[:10]],
        "csv_path": str(out_path),
    }


if __name__ == "__main__":
    run()

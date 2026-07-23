#!/usr/bin/env python3
"""Sync every available Super Lotto (大乐透) draw from the official Sporttery web API."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

API_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "draws.json"
PAGE_SIZE = 100
MAX_PAGES = 100
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.lottery.gov.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
    ),
}


def request_page(page_no: int) -> dict:
    params = {
        "gameNo": "85",
        "provinceId": "0",
        "pageSize": str(PAGE_SIZE),
        "isVerify": "1",
        "pageNo": str(page_no),
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None

    for attempt in range(1, 5):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or "value" not in payload:
                raise RuntimeError(f"Unexpected API response on page {page_no}")
            return payload
        except Exception as exc:
            last_error = exc
            if attempt == 4:
                break
            time.sleep(attempt * 3)

    raise RuntimeError(f"Failed to fetch page {page_no}: {last_error}")


def parse_record(record: dict) -> dict | None:
    issue = str(record.get("lotteryDrawNum", "")).strip()
    draw_date = str(record.get("lotteryDrawTime", "")).strip()[:10]
    result = str(record.get("lotteryDrawResult", "")).strip().split()

    if not issue or len(draw_date) != 10 or len(result) < 7:
        return None

    front = result[:5]
    back = result[5:7]

    try:
        front_int = [int(n) for n in front]
        back_int = [int(n) for n in back]
    except ValueError:
        return None

    if (
        len(set(front_int)) != 5
        or len(set(back_int)) != 2
        or not all(1 <= n <= 35 for n in front_int)
        or not all(1 <= n <= 12 for n in back_int)
    ):
        return None

    return {
        "issue": issue,
        "date": draw_date,
        "front": " ".join(f"{n:02d}" for n in front_int),
        "back": " ".join(f"{n:02d}" for n in back_int),
        "status": "已同步",
        "sales": record.get("lotterySaleAmount"),
        "pool": record.get("poolBalanceAfterdraw"),
    }


def main() -> None:
    records_by_issue: dict[str, dict] = {}
    total_hint: int | None = None

    for page_no in range(1, MAX_PAGES + 1):
        payload = request_page(page_no)
        value = payload.get("value") or {}
        records = value.get("list") or []

        if total_hint is None:
            for key in ("total", "totalCount", "recordCount"):
                try:
                    if value.get(key) is not None:
                        total_hint = int(value[key])
                        break
                except (TypeError, ValueError):
                    pass

        if not records:
            break

        before = len(records_by_issue)
        for record in records:
            parsed = parse_record(record)
            if parsed:
                records_by_issue[parsed["issue"]] = parsed

        added = len(records_by_issue) - before
        print(f"page={page_no} received={len(records)} added={added} total={len(records_by_issue)}")

        if total_hint and len(records_by_issue) >= total_hint:
            break
        if len(records) < PAGE_SIZE:
            break
        if added == 0:
            break

        time.sleep(0.35)

    if len(records_by_issue) < 100:
        raise RuntimeError(
            f"Only {len(records_by_issue)} valid draws were fetched; refusing to replace the archive."
        )

    draws = sorted(
        records_by_issue.values(),
        key=lambda item: (item["date"], int(item["issue"])),
        reverse=True,
    )

    synced_at = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    payload = {
        "meta": {
            "game": "超级大乐透",
            "gameNo": "85",
            "total": len(draws),
            "latestIssue": draws[0]["issue"],
            "latestDate": draws[0]["date"],
            "earliestIssue": draws[-1]["issue"],
            "earliestDate": draws[-1]["date"],
            "syncedAt": synced_at,
            "source": "中国体育彩票官方历史开奖接口",
            "sourceUrl": API_URL,
        },
        "draws": draws,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Saved {len(draws)} draws: "
        f"{draws[-1]['issue']} ({draws[-1]['date']}) -> "
        f"{draws[0]['issue']} ({draws[0]['date']})"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Synchronize the complete available Super Lotto (大乐透) draw archive."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

OFFICIAL_API_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
MIRROR_URL = "https://raw.githubusercontent.com/yangxb919/lottery-data/main/data/dlt.json"
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


def fetch_json(url: str, attempts: int = 4) -> object:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                time.sleep(attempt * 3)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def normalize_numbers(values: object, expected: int, upper: int) -> list[int] | None:
    if isinstance(values, str):
        parts = values.split()
    elif isinstance(values, list):
        parts = values
    else:
        return None

    try:
        numbers = [int(value) for value in parts]
    except (TypeError, ValueError):
        return None

    if len(numbers) != expected or len(set(numbers)) != expected:
        return None
    if not all(1 <= number <= upper for number in numbers):
        return None
    return numbers


def build_record(
    issue: object,
    draw_date: object,
    front_values: object,
    back_values: object,
    source: str,
    sales: object = None,
    pool: object = None,
) -> dict | None:
    issue_text = str(issue or "").strip()
    date_text = str(draw_date or "").strip()[:10].replace("/", "-")
    front = normalize_numbers(front_values, 5, 35)
    back = normalize_numbers(back_values, 2, 12)

    if not issue_text or len(date_text) != 10 or front is None or back is None:
        return None

    return {
        "issue": issue_text,
        "date": date_text,
        "front": " ".join(f"{number:02d}" for number in front),
        "back": " ".join(f"{number:02d}" for number in back),
        "status": "已同步",
        "source": source,
        "sales": sales,
        "pool": pool,
    }


def fetch_official() -> dict[str, dict]:
    records_by_issue: dict[str, dict] = {}
    total_hint: int | None = None

    for page_no in range(1, MAX_PAGES + 1):
        params = {
            "gameNo": "85",
            "provinceId": "0",
            "pageSize": str(PAGE_SIZE),
            "isVerify": "1",
            "pageNo": str(page_no),
        }
        payload = fetch_json(f"{OFFICIAL_API_URL}?{urllib.parse.urlencode(params)}")
        if not isinstance(payload, dict):
            raise RuntimeError("Official API returned a non-object response")

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
        for source_record in records:
            result = str(source_record.get("lotteryDrawResult", "")).strip().split()
            record = build_record(
                source_record.get("lotteryDrawNum"),
                source_record.get("lotteryDrawTime"),
                result[:5],
                result[5:7],
                "中国体育彩票官方接口",
                source_record.get("lotterySaleAmount"),
                source_record.get("poolBalanceAfterdraw"),
            )
            if record:
                records_by_issue[record["issue"]] = record

        added = len(records_by_issue) - before
        print(
            f"official page={page_no} received={len(records)} "
            f"added={added} total={len(records_by_issue)}"
        )

        if total_hint and len(records_by_issue) >= total_hint:
            break
        if len(records) < PAGE_SIZE or added == 0:
            break
        time.sleep(0.35)

    return records_by_issue


def fetch_mirror() -> dict[str, dict]:
    payload = fetch_json(MIRROR_URL)
    if not isinstance(payload, list):
        raise RuntimeError("Mirror returned a non-list response")

    records_by_issue: dict[str, dict] = {}
    for source_record in payload:
        record = build_record(
            source_record.get("issue"),
            source_record.get("date"),
            source_record.get("front"),
            source_record.get("back"),
            str(source_record.get("source") or "500.com"),
        )
        if record:
            records_by_issue[record["issue"]] = record

    print(f"mirror received={len(payload)} valid={len(records_by_issue)}")
    return records_by_issue


def read_existing() -> dict[str, dict]:
    if not OUTPUT.exists():
        return {}
    try:
        payload = json.loads(OUTPUT.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("draws", [])
        records: dict[str, dict] = {}
        for source_record in rows:
            record = build_record(
                source_record.get("issue"),
                source_record.get("date"),
                source_record.get("front"),
                source_record.get("back"),
                str(source_record.get("source") or "历史数据库"),
                source_record.get("sales"),
                source_record.get("pool"),
            )
            if record:
                records[record["issue"]] = record
        return records
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> None:
    combined = read_existing()
    sources_used: list[str] = []
    errors: list[str] = []

    try:
        mirror = fetch_mirror()
        combined.update(mirror)
        sources_used.append("500.com 全量历史镜像")
    except Exception as exc:
        errors.append(f"mirror: {exc}")
        print(errors[-1])

    try:
        official = fetch_official()
        combined.update(official)
        sources_used.append("中国体育彩票官方接口")
    except Exception as exc:
        errors.append(f"official: {exc}")
        print(errors[-1])

    if len(combined) < 1000:
        raise RuntimeError(
            f"Only {len(combined)} valid draws are available; refusing to replace the archive. "
            + " | ".join(errors)
        )

    draws = sorted(
        combined.values(),
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
            "source": " + ".join(sources_used),
            "sourceUrls": [OFFICIAL_API_URL, MIRROR_URL],
            "warnings": errors,
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

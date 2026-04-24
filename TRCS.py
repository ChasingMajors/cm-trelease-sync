import json
import os
import re
import sys
from datetime import datetime

import requests
from playwright.sync_api import sync_playwright


RELEASE_CALENDAR_URL = "https://www.topps.com/release-calendar"
DEFAULT_TIMEOUT_MS = 45000


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def normalize_source_key(value: str) -> str:
    value = normalize_space(value).lower()
    value = value.replace("®", "")
    value = re.sub(r"[^\w\s-]+", " ", value)
    return normalize_space(value)


def infer_sport(title: str) -> str:
    lower = title.lower()
    if "baseball" in lower:
        return "Baseball"
    if "football" in lower:
        return "Football"
    if "basketball" in lower:
        return "Basketball"
    if "hockey" in lower:
        return "Hockey"
    if "uefa" in lower or "premier league" in lower or "soccer" in lower:
        return "Soccer"
    return ""


def split_year_and_title(text: str) -> tuple[str, str]:
    text = normalize_space(text)
    for pattern in (
        r"^((?:19|20)\d{2}-\d{2})\s+(.+)$",
        r"^((?:19|20)\d{2})\s+(.+)$",
        r"^(.+)\s+((?:19|20)\d{2}-\d{2})$",
        r"^(.+)\s+((?:19|20)\d{2})$",
    ):
        match = re.match(pattern, text)
        if match:
            groups = match.groups()
            if re.match(r"^(19|20)\d{2}(?:-\d{2})?$", groups[0]):
                return groups[0], text
            return groups[1], text
    return "", text


def extract_calendar_year(value: str) -> str:
    raw = normalize_space(value)
    if re.match(r"^(19|20)\d{2}$", raw):
        return raw
    match = re.match(r"^((?:19|20)\d{2})-\d{2}$", raw)
    if match:
        return match.group(1)
    return ""


def build_iso_date(month_abbr: str, day: str, year_value: str) -> str:
    month_map = {
        "Jan": "01",
        "Feb": "02",
        "Mar": "03",
        "Apr": "04",
        "May": "05",
        "Jun": "06",
        "Jul": "07",
        "Aug": "08",
        "Sep": "09",
        "Oct": "10",
        "Nov": "11",
        "Dec": "12",
    }
    month = month_map.get(month_abbr, "")
    year = extract_calendar_year(year_value)
    if not month or not year:
        return ""
    return f"{year}-{month}-{int(day):02d}"


def parse_calendar_line(line: str, section: str) -> dict | None:
    if not re.match(r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),", line, re.I):
        return None

    normalized = re.sub(r"\s+Notify me$", "", line, flags=re.I)
    normalized = re.sub(r"\s+Available now$", "", normalized, flags=re.I)
    normalized = normalize_space(normalized)

    match = re.match(
        r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+at\s+\d{1,2}:\d{2}\s+[AP]M\s+UTC)?\s+(.+)$",
        normalized,
    )
    if not match:
        return None

    month_abbr = match.group(2)
    day = match.group(3)
    remainder = normalize_space(match.group(4))
    if not remainder:
        return None

    year, title = split_year_and_title(remainder)
    if not title:
        return None

    release_date = build_iso_date(month_abbr, day, year) if year else ""
    status = "Spotlight" if section == "release_spotlight" else "Upcoming"

    return {
        "releaseDate": release_date,
        "sport": infer_sport(title),
        "manufacturer": "Topps",
        "product": title,
        "setName": title,
        "format": "",
        "status": status,
        "checklistUrl": f"/checklists/?q={requests.utils.quote(title)}",
        "vaultUrl": f"/vault/?q={requests.utils.quote(title)}",
        "source": "topps_calendar",
        "sourceKey": normalize_source_key(title),
        "sourceUrl": RELEASE_CALENDAR_URL,
        "sourceSection": section,
        "lastSyncedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }


def dedupe_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for row in rows:
        key = (
            row.get("sourceKey", "").lower(),
            row.get("releaseDate", "").lower(),
            row.get("sourceSection", "").lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def lines_from_text(text: str) -> list[str]:
    return [line for line in (normalize_space(part) for part in text.splitlines()) if line]


def parse_calendar_text(text: str) -> list[dict]:
    lines = lines_from_text(text)
    rows = []
    section = ""

    for line in lines:
        lower = line.lower()
        if "dropping soon" in lower:
            section = "dropping_soon"
            continue
        if "release spotlight" in lower:
            section = "release_spotlight"
            continue
        if lower in ("products", "customer service", "corporate"):
            section = ""
            continue

        parsed = parse_calendar_line(line, section or "calendar")
        if parsed:
            rows.append(parsed)

    return dedupe_rows(rows)


def extract_rows_from_html(html: str) -> list[dict]:
    text = re.sub(r"<script[\s\S]*?</script>", "\n", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:br|p|div|section|article|li|h1|h2|h3|h4|h5|h6|span|a)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return parse_calendar_text(text)


def scrape_release_calendar() -> list[dict]:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            )
        )
        page.goto(RELEASE_CALENDAR_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        page.wait_for_timeout(5000)

        body_text = page.locator("body").inner_text(timeout=DEFAULT_TIMEOUT_MS)
        html = page.content()
        browser.close()

    rows = parse_calendar_text(body_text)
    if rows:
        return rows

    rows = extract_rows_from_html(html)
    if rows:
        return rows

    debug_payload = {
        "body_preview": body_text[:4000],
        "html_preview": html[:4000],
    }
    raise RuntimeError("No release rows were parsed from the page. Debug: " + json.dumps(debug_payload))


def post_rows_to_webhook(rows: list[dict]) -> dict:
    webhook_url = os.environ.get("TOPPS_SYNC_WEBHOOK_URL", "").strip()
    webhook_token = os.environ.get("TOPPS_SYNC_WEBHOOK_TOKEN", "").strip()

    if not webhook_url:
        raise RuntimeError("Missing TOPPS_SYNC_WEBHOOK_URL environment variable.")

    payload = {
        "action": "sync_topps_release_rows",
        "token": webhook_token,
        "rows": rows,
    }

    response = requests.post(
        webhook_url,
        headers={"Content-Type": "text/plain;charset=utf-8"},
        data=json.dumps(payload),
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def main() -> int:
    try:
        rows = scrape_release_calendar()
        print(json.dumps({"parsed_count": len(rows), "rows": rows[:10]}, indent=2))

        if os.environ.get("TOPPS_SYNC_DRY_RUN", "").lower() == "true":
            print("Dry run enabled. Skipping webhook sync.")
            return 0

        result = post_rows_to_webhook(rows)
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        print(f"TRCS failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

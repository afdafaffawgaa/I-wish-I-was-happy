#!/usr/bin/env python3
"""LARRY FiT 下館店の Google Maps Popular Times を SerpApi から取得する。

Runs without third-party Python packages; API credentials supplied by environment.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONFIG = ROOT / "config.json"
API_URL = "https://serpapi.com/search.json"
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
JST = ZoneInfo("Asia/Tokyo")


class CollectionError(RuntimeError):
    pass


def get_json(params: dict[str, str], api_key: str) -> dict:
    # SerpApi documents GET. GitHub Actions masks the secret; do not print request URLs.
    url = API_URL + "?" + urllib.parse.urlencode({**params, "api_key": api_key})
    req = urllib.request.Request(
        url, headers={"User-Agent": "LarryFitPopularTimesMonitor/1.0"}, method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=50) as response:
            result = json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise CollectionError(f"SerpApi connection error: {exc}") from exc
    if not isinstance(result, dict):
        raise CollectionError("Invalid API response")
    if result.get("error"):
        raise CollectionError(f"SerpApi error: {result['error']}")
    return result


def matches_target(name: str, address: str) -> bool:
    """Never silently select LifeFit or another location/brand."""
    name_ok = bool(re.search(r"larry\s*[- ]?\s*fit|ラリ[ーィ]フィット", name, flags=re.I))
    if not name_ok:
        return False
    if address and not any(keyword in address.lower() for keyword in ["筑西", "乙863", "乙８６３", "chikusei", "863-2"]):
        return False
    return True


def find_place(api_key: str, config: dict) -> dict:
    existing_path = DATA_DIR / "location.json"
    manually_configured = os.getenv("SERPAPI_PLACE_ID", "").strip()
    if manually_configured:
        return {"place_id": manually_configured, "source": "SERPAPI_PLACE_ID"}
    if existing_path.is_file():
        cached = json.loads(existing_path.read_text(encoding="utf-8"))
        if cached.get("place_id") or cached.get("data"):
            return cached

    result = get_json({
        "engine": "google_maps", "type": "search", "q": config["search_query"],
        "hl": "en", "gl": "jp", "ll": "@36.3077,139.978,14z",
    }, api_key)
    candidates = result.get("local_results") or []
    if not candidates and isinstance(result.get("place_results"), dict):
        candidates = [result["place_results"]]
    for item in candidates:
        name = str(item.get("title", ""))
        address = str(item.get("address", ""))
        if not matches_target(name, address):
            continue
        location = {"title": name, "address": address, "source": "SerpApi Google Maps Search"}
        if item.get("place_id"):
            location["place_id"] = item["place_id"]
        elif item.get("data_id") and item.get("gps_coordinates"):
            coords = item["gps_coordinates"]
            if "latitude" not in coords or "longitude" not in coords:
                continue
            location["data"] = (
                f"!4m5!3m4!1s{item['data_id']}!8m2!3d"
                f"{coords['latitude']}!4d{coords['longitude']}"
            )
        else:
            continue
        return location
    raise CollectionError(
        "LARRY FiT 下館店 (筑西市乙863-2) not found in Google Maps search; "
        "check the listing, or set the SERPAPI_PLACE_ID secret."
    )


def hour_from_time(value: str) -> int | None:
    """SerpApi's `hl=en` time strings: '6 AM', '12 PM', '9:00 PM'."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"\s*(\d{1,2})(?::\d{2})?\s*(AM|PM)\s*", value, flags=re.I)
    if not match:
        return None
    n = int(match.group(1))
    if not 1 <= n <= 12:
        return None
    return n % 12 + (12 if match.group(2).upper() == "PM" else 0)


def score_or_none(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 <= value <= 100:
        return None
    return round(float(value), 2)


def normalize_popular_times(popular: dict, now: datetime) -> tuple[dict, dict | None]:
    graph = popular.get("graph_results") or {}
    weekly = {day: [None] * 24 for day in DAYS}
    live = None
    for day in DAYS:
        entries = graph.get(day) or []
        for row in entries:
            hour = hour_from_time(row.get("time", ""))
            if hour is None:
                continue
            score = score_or_none(row.get("busyness_score"))
            if score is not None:
                weekly[day][hour] = score
            # Google may publish a live score only for the current hour.
            live_score = score_or_none(row.get("live_busyness_score"))
            if live_score is not None and (row.get("current") is True or day == DAYS[now.weekday()] and hour == now.hour):
                live = {"day": day, "hour": hour, "score": live_score,
                        "typical_score": score, "info": str(row.get("info", ""))}
    return weekly, live


def write_json_atomic(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def graph_count(weekly: dict) -> int:
    return sum(score is not None for hours in weekly.values() for score in hours)


def read_previous() -> dict:
    path = DATA_DIR / "latest.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def try_google_search(api_key: str, config: dict, now: datetime) -> tuple[dict, dict | None, dict]:
    # A second, documented SerpApi route. Google Search sometimes exposes
    # popular_times inside knowledge_graph even when Google Maps Place does not.
    result = get_json({
        "engine": "google",
        "q": "LARRYFIT 下館店 筑西市 乙863-2",
        "hl": "en", "gl": "jp", "google_domain": "google.co.jp",
    }, api_key)
    kg = result.get("knowledge_graph") or {}
    title = str(kg.get("title") or "")
    address = str(kg.get("address") or "")
    if not matches_target(title, address):
        return empty_weekly(), None, {
            "result": "not_the_target", "knowledge_graph_title": title[:120],
            "knowledge_graph_present": bool(kg),
        }
    popular = kg.get("popular_times") or {}
    weekly, live = normalize_popular_times(popular, now)
    return weekly, live, {
        "result": "graph_found" if graph_count(weekly) else "no_graph",
        "knowledge_graph_title": title[:120],
        "popular_times_present": bool(popular),
        "graph_hours": graph_count(weekly),
    }


def empty_weekly() -> dict:
    return {day: [None] * 24 for day in DAYS}


def should_search(now: datetime, previous: dict) -> bool:
    # In the no-data case, limit the fallback to once per JST calendar day.
    last_attempt = str((previous.get("diagnostics") or {}).get("google_search_last_attempt_jst") or "")
    return not last_attempt.startswith(now.date().isoformat())


def collect() -> dict:
    api_key = os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key:
        raise CollectionError("SERPAPI_API_KEY is missing. Add it as a GitHub Actions secret.")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    now = datetime.now(JST)
    previous = read_previous()
    location = find_place(api_key, config)

    # Keep a record of fallback attempts across GitHub Actions runs.
    last_search_at = (previous.get("diagnostics") or {}).get("google_search_last_attempt_jst")
    diagnostics = {"google_search_last_attempt_jst": last_search_at, "attempts": []}
    weekly, live = empty_weekly(), None
    source_engine = None
    place_name = str(location.get("title", config.get("name", "")))
    place_address = str(location.get("address", config.get("address", "")))

    # Once the backup route works, check it first on later runs. Otherwise
    # prefer the Maps Place endpoint because it has a verified place ID.
    search_first = previous.get("source_engine") == "google_search_knowledge_graph" and previous.get("status") == "ok"
    if search_first:
        try:
            weekly_s, live_s, diag = try_google_search(api_key, config, now)
            diagnostics["google_search_last_attempt_jst"] = now.isoformat(timespec="seconds")
            diagnostics["attempts"].append({"engine": "google_search_knowledge_graph", **diag})
            if graph_count(weekly_s):
                weekly, live, source_engine = weekly_s, live_s, "google_search_knowledge_graph"
        except CollectionError as exc:
            diagnostics["google_search_last_attempt_jst"] = now.isoformat(timespec="seconds")
            diagnostics["attempts"].append({"engine": "google_search_knowledge_graph", "result": "request_failed", "error_type": type(exc).__name__})

    if not source_engine:
        params = {"engine": "google_maps", "hl": "en", "gl": "jp"}
        if location.get("place_id"):
            params["place_id"] = location["place_id"]
        elif location.get("data"):
            params.update({"type": "place", "data": location["data"]})
        else:
            raise CollectionError("No valid place identifier")

        result = get_json(params, api_key)
        place = result.get("place_results") or {}
        title = str(place.get("title") or "")
        address = str(place.get("address") or "")
        if not matches_target(title, address):
            raise CollectionError(f"Wrong place returned: {title!r}, {address!r}; no data overwritten")
        place_name, place_address = title, address
        location = {"title": title, "address": address,
                    "place_id": place.get("place_id") or location.get("place_id"),
                    "source": "SerpApi Google Maps Place"}
        if not location.get("place_id"):
            location["data"] = params.get("data", "")
        write_json_atomic(DATA_DIR / "location.json", location)

        popular = place.get("popular_times") or {}
        weekly_m, live_m = normalize_popular_times(popular, now)
        diagnostics["attempts"].append({
            "engine": "google_maps_place", "result": "graph_found" if graph_count(weekly_m) else "no_graph",
            "popular_times_present": bool(popular), "graph_hours": graph_count(weekly_m),
        })
        if graph_count(weekly_m):
            weekly, live, source_engine = weekly_m, live_m, "google_maps_place"

    if not source_engine and not search_first and should_search(now, previous):
        try:
            weekly_s, live_s, diag = try_google_search(api_key, config, now)
            diagnostics["google_search_last_attempt_jst"] = now.isoformat(timespec="seconds")
            diagnostics["attempts"].append({"engine": "google_search_knowledge_graph", **diag})
            if graph_count(weekly_s):
                weekly, live, source_engine = weekly_s, live_s, "google_search_knowledge_graph"
        except CollectionError as exc:
            diagnostics["google_search_last_attempt_jst"] = now.isoformat(timespec="seconds")
            diagnostics["attempts"].append({"engine": "google_search_knowledge_graph", "result": "request_failed", "error_type": type(exc).__name__})

    populated = graph_count(weekly)
    status = "ok" if populated else "unavailable"
    latest = {
        "status": status,
        "fetched_at_jst": now.isoformat(timespec="seconds"),
        "source": ("Google Search Knowledge Graph via SerpApi" if source_engine == "google_search_knowledge_graph"
                   else "Google Maps via SerpApi"),
        "source_engine": source_engine,
        "place": {"name": place_name, "address": place_address},
        "unit": "relative_busyness_0_to_100_not_number_of_people",
        "days": weekly, "live": live,
        "diagnostics": diagnostics,
        "note": ("Neither tested SerpApi route returned a Popular Times graph for this place; this is not zero crowd."
                 if status == "unavailable" else "Typical scores are estimates, not live head counts."),
    }
    write_json_atomic(DATA_DIR / "latest.json", latest)
    history_row = {
        "fetched_at_jst": latest["fetched_at_jst"], "status": status,
        "source_engine": source_engine, "live": live,
        "typical_current_hour": weekly[DAYS[now.weekday()]][now.hour],
        "graph_values": populated,
    }
    with (DATA_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(history_row, ensure_ascii=False, allow_nan=False) + "\n")
    return {"status": status, "fetched_at_jst": latest["fetched_at_jst"],
            "source_engine": source_engine, "graph_values": populated,
            "live": live, "diagnostics": diagnostics}


if __name__ == "__main__":
    try:
        result = collect()
        print(json.dumps(result, ensure_ascii=False))
        # unavailable is not an exception: Google can genuinely omit this section.
    except (CollectionError, ValueError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"Collection failed: {exc}", file=sys.stderr)
        sys.exit(1)

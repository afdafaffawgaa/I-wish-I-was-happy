#!/usr/bin/env python3
"""Experimental Google Maps UI popular-times collector for LARRYFIT Shimodate.

This reads publicly displayed information from the browser. Google doesn't offer an
official Popular Times API. The interface may change and browser runs can be blocked.
The script NEVER substitutes invented crowd numbers for unparsed data.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DEBUG = ROOT / 'browser_diagnostics'
DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
CHRONO = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday']
PLACE_ID = 'ChIJmam1ug5VH2ARWhSeQUqRe1g'
MAP_URL = 'https://www.google.com/maps/search/?' + urlencode({
    'api': '1', 'query': '「マッチョのいない月3,300円24時間ジム」LARRYFIT 筑西市乙863-2',
    'query_place_id': PLACE_ID, 'hl': 'en',
})
JST = ZoneInfo('Asia/Tokyo')
PERCENT = re.compile(r'(?<!\d)(100|\d{1,2})\s*%')
AMPM = re.compile(r'\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*([AP])\.?M\.?\b', re.I)
CLOCK24 = re.compile(r'(?<!\d)([01]?\d|2[0-3]):[0-5]\d(?!\d)')
JAPANESE_CLOCK = re.compile(r'(午前|午後)?\s*(\d{1,2})\s*時')


def empty_weekly():
    return {d: [None] * 24 for d in DAYS}


def count_values(days):
    return sum(v is not None for hours in days.values() for v in hours)


def hour_of(label):
    txt = str(label).replace('\u202f', ' ').replace('\xa0', ' ')
    m = AMPM.search(txt)
    if m:
        h = int(m.group(1))
        if not 1 <= h <= 12:
            return None
        return (h % 12) + (12 if m.group(3).upper() == 'P' else 0)
    m = CLOCK24.search(txt)
    if m:
        return int(m.group(1))
    m = JAPANESE_CLOCK.search(txt)
    if m:
        prefix, h = m.group(1), int(m.group(2))
        if h > 23 or (prefix is not None and h > 12):
            return None
        if prefix == '午後':
            return h % 12 + 12
        if prefix == '午前':
            return h % 12
        return h
    return None


def parse_bar(label):
    """Return (hour, usual_score, live_score); no unsupported inference."""
    hour = hour_of(label)
    nums = [int(x) for x in PERCENT.findall(str(label))]
    if hour is None or not nums:
        return None
    txt = str(label).casefold()
    if len(nums) >= 2 and ('currently' in txt or 'right now' in txt or '現在' in txt):
        # Google sometimes puts the live estimate first and usual estimate second.
        return (hour, nums[1], nums[0])
    return (hour, nums[0], None)


def parse_groups(groups, now):
    days = empty_weekly()
    live = None
    for group in groups:
        day = group.get('day')
        if day not in DAYS:
            continue
        for label in group.get('labels', []):
            parsed = parse_bar(label)
            if not parsed:
                continue
            hour, typical, current = parsed
            days[day][hour] = typical
            if current is not None and day == DAYS[now.weekday()] and hour == now.hour:
                live = {'day': day, 'hour': hour, 'score': current,
                        'typical_score': typical, 'info': 'From Google Maps accessibility label'}
    return days, live


# Browser-side extraction. The first strategy follows the public open-source
# populartimes.js HTML structure: div[aria-label="Popular times at NAME"]
# and its final child containing 7 day groups starting on Sunday.
EXTRACT_JS = r'''() => {
    const selector = '[aria-label^="Popular times at"], [aria-label*="混雑する時間帯"]';
    const roots = [...document.querySelectorAll(selector)];
    const labels = el => [...el.querySelectorAll('[aria-label]')]
        .map(n => n.getAttribute('aria-label')).filter(Boolean);
    const dayNames = ['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
    const result = {rootCount: roots.length, groups: [], labelsSample: [], placeTitle: '', pageTitle: document.title};
    const h1 = document.querySelector('h1');
    result.placeTitle = h1 ? h1.textContent.trim().slice(0,160) : '';
    for (const root of roots) {
        const last = root.lastElementChild;
        const kids = last ? [...last.children] : [];
        // Old layout keeps all seven day charts in order, including hidden ones.
        if (kids.length >= 7) {
            const candidate = kids.slice(0,7).map((node,i)=>({day: dayNames[i], labels: labels(node)}));
            if (candidate.some(c=>c.labels.some(s=>/%/.test(s)))) {
                result.groups.push(...candidate);
                break;
            }
        }
    }
    if (!result.groups.length) {
        // Collect candidates without assigning them to the wrong day. The
        // controller may have only the selected day; that needs another method.
        const root = roots[0];
        if (root) result.labelsSample = labels(root).slice(0,160);
    }
    // Lightweight diagnostic sample when the expected graph structure changes.
    if (!result.labelsSample.length) {
        result.labelsSample = [...document.querySelectorAll('[aria-label]')]
          .map(e=>e.getAttribute('aria-label')).filter(s=>/busy|popular|%|混雑|時間帯/i.test(s||''))
          .slice(0,100);
    }
    return result;
}'''


def extract_single_day_from_dropdown(page):
    """Best-effort newer layout: choose each weekday in the 'Popular times' day dropdown.

    No data is attributed to a day unless the day selection is verified.
    """
    found = []
    # Try the known Google Maps day-selector control inside the Popular times region.
    # This is intentionally conservative: a failed selector returns empty, not made-up data.
    js = r'''() => {
        const head = [...document.querySelectorAll('*')].find(e => e.children.length === 0 &&
            /^(Popular times|混雑する時間帯)$/.test((e.textContent||'').trim()));
        if (!head) return null;
        let parent = head;
        for (let i=0;i<5;i++) {
            if (!parent.parentElement) break;
            parent = parent.parentElement;
            const buttons = [...parent.querySelectorAll('button,[role="button"],select')];
            if (buttons.length > 1 && buttons.length < 12) {
                return buttons.map(b=>({text:(b.textContent||'').trim(),aria:b.getAttribute('aria-label'),
                    title:b.getAttribute('title'),tag:b.tagName}));
            }
        }
        return null;
    }'''
    try:
        found = page.evaluate(js) or []
    except Exception:
        pass
    return found


def get_page(browser, locale, debug_prefix):
    page = browser.new_page(locale='ja-JP' if locale == 'ja' else 'en-US', viewport={'width': 1280, 'height': 1000})
    # Locale can affect UI labels and whether busy bars render; query_place_id
    # keeps us on the right listing rather than similarly named gyms.
    url = MAP_URL.replace('hl=en', f'hl={locale}')
    diagnostics = {'locale': locale, 'url_path': '/maps/search/', 'error': None}
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=55000)
        page.wait_for_timeout(6500)
        # Google sometimes needs the side-pane scrolled to load the chart.
        page.evaluate('''() => {
            let p = document.querySelector('[role="main"]');
            if(p) p.scrollTop = p.scrollHeight;
        }''')
        page.wait_for_timeout(1500)
        snapshot = page.evaluate(EXTRACT_JS)
        diagnostics.update(snapshot)
        seen_title = str(snapshot.get('placeTitle','')) + ' ' + str(snapshot.get('pageTitle',''))
        if not re.search(r'LARRY\s*[- ]?\s*FIT|マッチョのいない', seen_title, re.I):
            diagnostics['error'] = 'Wrong listing, or Google Maps did not render the target place title'
            return [], diagnostics
        diagnostics['day_controls'] = extract_single_day_from_dropdown(page)
        # Keep diagnostic image as a GitHub Actions artifact only, NOT in Pages.
        DEBUG.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(DEBUG / f'{debug_prefix}_{locale}.png'), full_page=False, timeout=10000)
        except Exception:
            pass
        return snapshot.get('groups', []), diagnostics
    except Exception as exc:
        diagnostics['error'] = f'{type(exc).__name__}: {str(exc)[:250]}'
        return [], diagnostics
    finally:
        page.close()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run():
    now = datetime.now(JST)
    diagnostics = []
    days, live = empty_weekly(), None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for locale in ('en', 'ja'):
                    groups, diag = get_page(browser, locale, 'larryfit')
                    diagnostics.append(diag)
                    parsed, maybe_live = parse_groups(groups, now)
                    if count_values(parsed) > count_values(days):
                        days, live = parsed, maybe_live
                    if count_values(days) >= 12:
                        break
            finally:
                browser.close()
    except Exception as exc:
        diagnostics.append({'error': f'{type(exc).__name__}: {str(exc)[:300]}'})
    total = count_values(days)
    status = 'ok' if total else 'unavailable'
    output = {
        'status': status, 'fetched_at_jst': now.isoformat(timespec='seconds'),
        'source': 'Google Maps web UI (Playwright; experimental)',
        'source_engine': 'browser_google_maps' if total else None,
        'place': {'name': '「マッチョのいない月3,300円24時間ジム」LARRYFIT',
                  'address': '〒308-0041 茨城県筑西市乙863-2 やますビル2号館', 'place_id': PLACE_ID},
        'unit': 'relative_busyness_0_to_100_not_number_of_people',
        'days': days, 'live': live,
        'diagnostics': diagnostics,
        'note': ('Found some public popular times labels; scores are relative and not actual headcounts.'
                 if total else 'Browser did not yield parseable Popular Times; this is NOT evidence that the store is empty.'),
    }
    DATA.mkdir(exist_ok=True)
    save_json(DATA / 'latest.json', output)
    with (DATA / 'history.jsonl').open('a', encoding='utf-8') as fh:
        fh.write(json.dumps({
            'fetched_at_jst': output['fetched_at_jst'], 'status': status,
            'source_engine': output['source_engine'], 'live': live,
            'graph_values': total,
            'typical_current_hour': days[DAYS[now.weekday()]][now.hour],
        }, ensure_ascii=False) + '\n')
    print(json.dumps({'status': status, 'graph_values': total,
                      'root_count': [v.get('rootCount',0) for v in diagnostics],
                      'errors': [v.get('error') for v in diagnostics if v.get('error')]}, ensure_ascii=False))
    return total


if __name__ == '__main__':
    run()

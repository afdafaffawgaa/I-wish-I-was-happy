#!/usr/bin/env python3
"""LARRYFIT fresh Google HTML collector v8.

Tries Google Search's weekly popular-times day switcher first; falls back to
Google Maps's seven daily aria-label charts. It never ships cached/hardcoded
popular-times values as if fetched today. No paid API or extension.

WARNING: Google may restrict automated sessions; an offline parser test is
not proof this fetch will work on GitHub Actions.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
DEBUG = ROOT / 'browser_diagnostics'
DAYS = ('sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday')
PLACE = '「マッチョのいない月3,300円24時間ジム」LARRYFIT'
SEARCH_URL = 'https://www.google.com/search?' + urlencode({'q': PLACE, 'hl': 'ja', 'gl': 'jp'})
MAPS_URL = ('https://www.google.com/maps/place/'
 '%E3%80%8C%E3%83%9E%E3%83%83%E3%83%81%E3%83%A7%E3%81%AE%E3%81%84%E3%81%AA%E3%81%84%E6%9C%883,300%E5%86%8624%E6%99%82%E9%96%93%E3%82%B8%E3%83%A0%E3%80%8DLARRYFIT/'
 '@36.3015197,139.9773529,1093m/data=!3m2!1e3!4b1!4m6!3m5!1s0x601f550ebab5a999:0x587b914a419e145a!8m2!3d36.3015197!4d139.9773529!16s%2Fg%2F11vc2x23fh?hl=ja')

# CSS data-hour values 24..27 denote 00:00..03:00 of NEXT calendar day.
# Heights / 75px match the EXACT percentages in the user's supplied Search
# and Maps snippets on Tuesday; this is NOT a universal Google API guarantee.
SEARCH_JS = r'''() => {
  const root = document.querySelector('[data-attrid="kc:/local:busyness"]');
  if (!root) return {reason:'Search busy widget missing', selected:0, rows:[]};
  const active = root.querySelector('[data-day][aria-checked="true"]');
  const selected = active ? Number(active.getAttribute('data-day')) : 0;
  const bars = [...root.querySelectorAll('[data-hour]')];
  const rows = bars.map(el => {
    const h = Number(el.getAttribute('data-hour'));
    const label = el.getAttribute('aria-label') || '';
    const bar = el.querySelector('.cuRVnd');
    const cssHeight = bar ? parseFloat(bar.style.height) : NaN;
    const match = label.match(/混雑度は\s*(\d{1,3})\s*%/);
    const pct = match ? Number(match[1]) : (Number.isFinite(cssHeight) ? Math.round(cssHeight/75*100) : null);
    return {h,pct,estimated:!match,height:cssHeight};
  });
  return {selected,rows,title:document.title,hasWidget:true};
}'''

MAPS_JS = r'''() => {
  const region = [...document.querySelectorAll('[role="region"][aria-label]')]
     .find(e=>/混雑する時間帯/.test(e.getAttribute('aria-label')||'') && /LARRYFIT/i.test(e.getAttribute('aria-label')||''));
  if (!region) return {reason:'Maps popular-times chart missing',days:[]};
  const sections = [...region.querySelectorAll('div.g2BVhd')];
  const days = sections.map(el => [...el.querySelectorAll('[role="img"][aria-label]')]
    .map(bar => bar.getAttribute('aria-label')));
  return {days,sectionCount:sections.length};
}'''


def from_search_days(results: dict[int, dict]):
    """Accept 7 graph days (1=Mon, 7=Sun), each containing 4..27."""
    if set(results) != set(range(1, 8)):
        raise ValueError(f'Search weekday switches incomplete: {sorted(results)}')
    graph = {}
    for daynum in range(1, 8):
        r = results[daynum]
        if int(r.get('selected', 0)) != daynum:
            raise ValueError(f'Wrong selected weekday: want={daynum}, seen={r.get("selected")}')
        hours = {}
        rows = r.get('rows') or []
        if len(rows) != 24:
            raise ValueError(f'Day {daynum} has {len(rows)} bars, expected 24')
        for bar in rows:
            h, value = bar.get('h'), bar.get('pct')
            if (not isinstance(h, int) or isinstance(h, bool) or not 4 <= h <= 27
                or not isinstance(value, (int, float)) or isinstance(value, bool)
                or not 0 <= value <= 100 or h in hours):
                raise ValueError(f'Invalid search bar: day={daynum} bar={bar}')
            hours[h] = int(round(value))
        if set(hours) != set(range(4,28)):
            raise ValueError(f'Day {daynum} hours not 4..27')
        graph[daynum % 7] = hours
    # Map 4..23 to graph day; 0..3 to previous graph day (24..27).
    days = {}
    for di, name in enumerate(DAYS):
        current = graph[di]
        previous = graph[(di-1) % 7]
        days[name] = [previous[h+24] if h < 4 else current[h] for h in range(24)]
    return days


def from_maps_labels(groups):
    """Seven Maps groups from Sunday to Saturday; each 4..27 rollover."""
    if len(groups) != 7:
        raise ValueError(f'Maps groups missing (got {len(groups)}, need 7)')
    graphs = {}
    pat = re.compile(r'(\d{1,2})時の混雑度は\s*(\d{1,3})\s*%')
    for day_idx, labels in enumerate(groups):
        if len(labels) != 24:
            raise ValueError(f'Maps group {day_idx} has {len(labels)} bars')
        values = {}
        for index, label in enumerate(labels):
            m = pat.search(label)
            if not m:
                raise ValueError(f'Unparseable aria label day={day_idx}: {label[:70]}')
            hour, pct = map(int, m.groups())
            expected = (index + 4) % 24
            if hour != expected or not 0 <= pct <= 100:
                raise ValueError(f'Unexpected bar order/value, day={day_idx} hour={hour}')
            values[index+4] = pct
        graphs[day_idx] = values
    return {name:[graphs[(di-1)%7][h+24] if h < 4 else graphs[di][h]
                  for h in range(24)] for di,name in enumerate(DAYS)}


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def diagnostic_screenshot(page, tag):
    DEBUG.mkdir(exist_ok=True)
    try:
        page.screenshot(path=str(DEBUG/(tag+'.png')), timeout=7000)
    except Exception:
        pass


def collect_search(browser, attempts):
    page = browser.new_page(locale='ja-JP', viewport={'width':1420,'height':1000})
    diag = {'source':'google_search', 'verified_days':[]}
    attempts.append(diag)
    try:
        page.goto(SEARCH_URL, wait_until='domcontentloaded', timeout=35000)
        try:
            page.locator('[data-attrid="kc:/local:busyness"] [data-hour]').first.wait_for(timeout=12000)
        except Exception:
            diagnostic_screenshot(page, 'search_widget_missing')
            raise ValueError('Google Search response did not contain popular-times HTML')
        result = {}
        for day in range(1,8):
            day_button = page.locator(f'[data-attrid="kc:/local:busyness"] [data-day="{day}"]')
            day_button.click(timeout=5000)
            page.wait_for_function('''n => {
              const root=document.querySelector('[data-attrid="kc:/local:busyness"]');
              const b=root && root.querySelector(`[data-day="${n}"]`);
              return b && b.getAttribute('aria-checked')==='true' && root.querySelectorAll('[data-hour]').length>=24;
            }''', arg=day, timeout=7000)
            page.wait_for_timeout(400)
            snapshot = page.evaluate(SEARCH_JS)
            result[day] = snapshot
            diag['verified_days'].append(day)
            diag[f'day_{day}_bars'] = len(snapshot.get('rows',[]))
        days = from_search_days(result)
        # Seven individually switched days must not all yield one frozen 24h series.
        if len({tuple(days[d]) for d in DAYS}) == 1:
            raise ValueError('All seven weekdays identical: potential frozen Google widget')
        diagnostic_screenshot(page, 'search_success')
        diag['status'] = 'success'
        return days, 'Google Search DOM height-calibrated (approximate 0-100)'
    except Exception as e:
        diag['status']='failed'; diag['reason']=f'{type(e).__name__}: {e}'[:350]
        diagnostic_screenshot(page, 'search_failed')
        return None, None
    finally:
        page.close()


def collect_maps(browser, attempts):
    page = browser.new_page(locale='ja-JP', viewport={'width':1440,'height':950})
    diag = {'source':'google_maps'}
    attempts.append(diag)
    try:
        page.goto(MAPS_URL, wait_until='domcontentloaded', timeout=35000)
        page.wait_for_timeout(3000)
        # Google Maps panel scrolls inside an overflow-y DIV, not window.scrollY.
        for _ in range(14):
            parsed = page.evaluate(MAPS_JS)
            if len(parsed.get('days',[])) == 7:
                break
            page.evaluate('''() => {
               const x=260,y=Math.min(590,innerHeight-170);
               const from=document.elementFromPoint(x,y);
               let el=from;
               while (el && !(el.scrollHeight>el.clientHeight+50 &&
                     /auto|scroll/.test(getComputedStyle(el).overflowY))) el=el.parentElement;
               if (el) el.scrollTop+=500;
            }''')
            page.mouse.move(260, min(590, 950-170))
            page.mouse.wheel(0,500)
            page.wait_for_timeout(600)
        parsed = page.evaluate(MAPS_JS)
        diag['group_count'] = len(parsed.get('days',[]))
        days=from_maps_labels(parsed.get('days',[]))
        diag['status']='success'
        diagnostic_screenshot(page, 'maps_success')
        return days,'Google Maps aria-label percentages (exact labels)'
    except Exception as e:
        diag['status']='failed'; diag['reason']=f'{type(e).__name__}: {e}'[:350]
        diagnostic_screenshot(page, 'maps_failed')
        return None,None
    finally:
        page.close()


def run():
    DATA.mkdir(exist_ok=True)
    timestamp = datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(timespec='seconds')
    attempts = []
    days = source = None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                days,source = collect_search(browser, attempts)
                if days is None:
                    days,source = collect_maps(browser, attempts)
            finally:
                browser.close()
    except Exception as e:
        attempts.append({'source':'browser_launch','status':'failed','reason':f'{type(e).__name__}: {e}'[:400]})
    success = days is not None and sum(len(x) for x in days.values()) == 168
    output = {
        'status':'ok' if success else 'unavailable',
        'fetched_at_jst':timestamp if success else None,
        'attempted_at_jst':timestamp,
        'source':source if success else None,
        'place':{'name':PLACE,'address':'茨城県筑西市乙863-2'},
        'unit':'relative_busyness_index_not_headcount',
        'days':days if success else {x:[None]*24 for x in DAYS},
        'live':None,
        'diagnostics':attempts,
        'note':('All 168 values fetched this run.' if success else
                'NO fresh Google popular-times values retrieved. Null is NOT zero. No old data substituted.')
    }
    save(DATA/'latest.json',output)
    with (DATA/'history.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'attempted_at_jst':timestamp,'status':output['status'],
            'fresh_hour_count':168 if success else 0,'source':source},ensure_ascii=False)+'\n')
    if not success:
        print('::warning title=LARRYFIT data unavailable::No fresh chart received. See latest.json diagnostics.')
    print(json.dumps({'status':output['status'],'fresh_hour_count':168 if success else 0,
                      'attempts':attempts},ensure_ascii=False))
    return bool(success)


if __name__=='__main__':
    run()

#!/usr/bin/env python3
"""
F1CC Wiki — Sync from Google Sheets (26_data tab)
Fetches the live sheet and rebuilds:
  data/races_2026.json      (F1 results)
  data/races_2026_f2.json   (F2 results)
  data/db.json              (standings for both series)

Sheet: GID 359936286  (26_data tab)

Layout — four sections, each identified by col A label:
  "F1 Quali"      → F1 qualifying positions
  "F1 Race"       → F1 race finishing positions (col A also carries race codes)
  "F2 Qualifying" → F2 qualifying positions
  "F2 Race"       → F2 race finishing positions

Driver rows (in every section):
  Col A: Nation flag code (EE, FI, DE, …)
  Col B: Driver code — this IS the canonical ID (ev_69, rk_99, …)
  Col C: Display name (informational only — not used as key)
  Col D+: Results per race, in the same order as the section's race-code header

Position encoding:
  7    = P7 finish
  7*   = P7 with fastest lap (+1 point in F1 feature races if pos ≤ 10)
  DNF  = Did Not Finish (0 points)
  NC   = Not Classified / Not Competing (skip — treat as absent)
  blank/0 = did not participate (skip)
"""

import json, os, re, sys, unicodedata
from io import BytesIO

import requests
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
SHEET_ID   = '1XJWNG1R74CADbob6mHo4D3G7DV8gxaQQKTDpHqu2Bqo'
SHEET_GID  = '359936286'    # 26_data tab  (race results)
CODES_GID  = '1937960697'   # codes tab    (driver registry)
CSV_URL    = (
    f'https://docs.google.com/spreadsheets/d/{SHEET_ID}'
    f'/export?format=csv&gid={SHEET_GID}'
)
CODES_URL  = (
    f'https://docs.google.com/spreadsheets/d/{SHEET_ID}'
    f'/export?format=csv&gid={CODES_GID}'
)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH  = os.path.join(DATA_DIR, 'db.json')
F1_OUT   = os.path.join(DATA_DIR, 'races_2026.json')
F2_OUT   = os.path.join(DATA_DIR, 'races_2026_f2.json')

F1_SEASON = '2026'
F2_SEASON = '2026_f2'

RACE_PTS      = {1:25, 2:18, 3:15, 4:12, 5:10, 6:8, 7:6, 8:4, 9:2, 10:1}
SPRINT_PTS    = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}
F2_SPRINT_PTS = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}

# F1 sprint race codes
SPRINTS = {'CHNS', 'SAUS', 'AUTS', 'NETS', 'USAS', 'BRAS'}

# Regex that matches valid driver codes: two lowercase letters + underscore + digits
DRIVER_CODE_RE = re.compile(r'^[a-z]{2}_\d+$')

RACE_META = {
    'AUS' : {'flag': '🇦🇺', 'circuit': 'Albert Park'},
    'CHNS': {'flag': '🇨🇳', 'circuit': 'Shanghai Sprint'},
    'CHN' : {'flag': '🇨🇳', 'circuit': 'Shanghai'},
    'JPN' : {'flag': '🇯🇵', 'circuit': 'Suzuka'},
    'BAH' : {'flag': '🇧🇭', 'circuit': 'Bahrain International'},
    'SAUS': {'flag': '🇸🇦', 'circuit': 'Jeddah Sprint'},
    'SAU' : {'flag': '🇸🇦', 'circuit': 'Jeddah Street'},
    'MIA' : {'flag': '🇺🇸', 'circuit': 'Miami International'},
    'CAN' : {'flag': '🇨🇦', 'circuit': 'Circuit Gilles Villeneuve'},
    'MON' : {'flag': '🇲🇨', 'circuit': 'Monaco'},
    'SPA' : {'flag': '🇪🇸', 'circuit': 'Circuit de Barcelona'},
    'AUTS': {'flag': '🇦🇹', 'circuit': 'Red Bull Ring Sprint'},
    'AUT' : {'flag': '🇦🇹', 'circuit': 'Red Bull Ring'},
    'BRI' : {'flag': '🇬🇧', 'circuit': 'Silverstone'},
    'GBR' : {'flag': '🇬🇧', 'circuit': 'Silverstone'},
    'BEL' : {'flag': '🇧🇪', 'circuit': 'Spa-Francorchamps'},
    'HUN' : {'flag': '🇭🇺', 'circuit': 'Hungaroring'},
    'NETS': {'flag': '🇳🇱', 'circuit': 'Zandvoort Sprint'},
    'NET' : {'flag': '🇳🇱', 'circuit': 'Zandvoort'},
    'ITA' : {'flag': '🇮🇹', 'circuit': 'Monza'},
    'IMO' : {'flag': '🇮🇹', 'circuit': 'Imola'},
    'AZE' : {'flag': '🇦🇿', 'circuit': 'Baku'},
    'SIN' : {'flag': '🇸🇬', 'circuit': 'Marina Bay'},
    'USAS': {'flag': '🇺🇸', 'circuit': 'COTA Sprint'},
    'USA' : {'flag': '🇺🇸', 'circuit': 'Circuit of the Americas'},
    'MEX' : {'flag': '🇲🇽', 'circuit': 'Hermanos Rodriguez'},
    'BRAS': {'flag': '🇧🇷', 'circuit': 'Interlagos Sprint'},
    'BRA' : {'flag': '🇧🇷', 'circuit': 'Interlagos'},
    'LVG' : {'flag': '🇺🇸', 'circuit': 'Las Vegas Street'},
    'ABU' : {'flag': '🇦🇪', 'circuit': 'Yas Marina'},
    'UAE' : {'flag': '🇦🇪', 'circuit': 'Yas Marina'},
    'QAT' : {'flag': '🇶🇦', 'circuit': 'Lusail'},
    'SPR' : {'flag': '🏁',  'circuit': 'Sprint Race'},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def country_flag_emoji(code):
    """Convert a 2-letter ISO country code to a flag emoji (e.g. 'FI' → '🇫🇮')."""
    code = str(code).strip().upper()
    if len(code) != 2 or not code.isalpha():
        return ''
    return ''.join(chr(0x1F1E6 + ord(c) - ord('A')) for c in code)


def sync_driver_metadata(db):
    """Fetch the codes sheet and update name/flag/number on every driver.

    Codes sheet columns (GID 1937960697):
      A: Code (e.g. ev_69)   B: Series   C: Driver Name
      D: Nation (2-letter ISO code, e.g. FI)   E: Number

    Creates new db.drivers entries for codes not yet present.
    """
    import csv
    from io import StringIO

    print(f'Fetching codes sheet (GID {CODES_GID})…')
    resp = requests.get(CODES_URL, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(StringIO(resp.content.decode('utf-8-sig')))

    created = updated = 0
    for row in reader:
        if not row:
            continue
        code = row[0].strip().lower()
        if not DRIVER_CODE_RE.match(code):
            continue  # header row or blank — skip

        name       = row[2].strip() if len(row) > 2 else ''
        nation     = row[3].strip() if len(row) > 3 else ''
        number_raw = row[4].strip() if len(row) > 4 else ''
        try:
            number = int(number_raw)
        except (ValueError, TypeError):
            number = None

        if code not in db['drivers']:
            db['drivers'][code] = {
                'flag':       nation.lower(),
                'name':       name,
                'number':     number,
                'seasons':    {},
                'photo':      None,
                'flag_emoji': country_flag_emoji(nation),
            }
            print(f'  + New driver: {code} = {name}')
            created += 1
        else:
            d = db['drivers'][code]
            if name:
                d['name'] = name
            if nation:
                d['flag']       = nation.lower()
                d['flag_emoji'] = country_flag_emoji(nation)
            if number is not None:
                d['number'] = number
            updated += 1

    print(f'✓ Driver metadata: {updated} updated, {created} created')


def parse_pos(raw):
    """Parse a result cell. Returns (position, fastest_lap_bool).

    Supported values:
      7     → (7, False)
      7*    → (7, True)   fastest lap
      DNF   → ('DNF', False)
      NC    → (None, False)  not classified / not competing — skip
      blank / 0 / nan → (None, False)  did not participate — skip
    """
    s = str(raw).strip()
    if s in ('nan', '0', '', 'NC'):
        return None, False
    fl = s.endswith('*')
    s  = s.rstrip('*').strip()
    if s.upper() in ('DNF', 'DSQ', 'RET'):
        return s.upper(), fl
    try:
        v = int(s)
        return (v if v > 0 else None), fl
    except ValueError:
        return None, False


def find_section(df, label):
    """Return the DataFrame row index where col A (iloc[0]) equals label."""
    for i, row in df.iterrows():
        if str(row.iloc[0]).strip() == label:
            return i
    return None


def get_race_codes(df, section_row):
    """Return the list of race codes for a section.

    Two layouts exist on the 26_data tab:
      - 'F1 Race' / 'F2 Race' / 'F2 Qualifying': race codes are in cols D+
        on the same row as the section label.
      - 'F1 Quali': the section label row has no race codes; they live on the
        NEXT row (the 'Nation,Code,Name,AUS,...' column-header row).

    We check the section label row first; if it has no codes, check the next row.
    """
    for r in [section_row, section_row + 1]:
        if r >= len(df):
            continue
        codes = [str(df.iloc[r, c]).strip() for c in range(3, df.shape[1])]
        codes = [c for c in codes if c not in ('', 'nan', 'TOTAL')]
        if codes:
            return codes
    return []


def make_map(df, section_row, max_rows=30):
    """Build {driver_code: [col-D .. last-col values]} for every driver row
    after section_row.

    Driver rows are identified by col B (iloc[1]) matching DRIVER_CODE_RE
    (e.g. 'ev_69').  Non-driver rows (blank rows, column-header rows like
    'Nation,Code,Name,...') are silently skipped.  Two consecutive blank col-B
    cells terminate the scan.
    """
    m = {}
    blank_streak = 0
    for i in range(section_row + 1, min(section_row + 1 + max_rows, len(df))):
        row  = df.iloc[i]
        code = str(row.iloc[1]).strip()
        if not code or code == 'nan':
            blank_streak += 1
            if blank_streak >= 2:
                break
            continue
        blank_streak = 0
        if not DRIVER_CODE_RE.match(code.lower()):
            continue  # header row or stray label — skip
        m[code] = [str(row.iloc[c]).strip() for c in range(3, df.shape[1])]
    return m


# ── Core builder ──────────────────────────────────────────────────────────────

def build_races(df, race_label, quali_label, season_key, db, is_f2=False):
    """Parse one series' results from the sheet.
    Returns a list of race dicts ready for the JSON output file.

    race_label / quali_label: section-header strings in col A of the sheet
      e.g. 'F1 Race' / 'F1 Quali'  or  'F2 Race' / 'F2 Qualifying'
    """
    race_row = find_section(df, race_label)
    if race_row is None:
        print(f'  WARNING: "{race_label}" section not found — skipping {season_key}')
        return []

    quali_row = find_section(df, quali_label)

    race_codes = get_race_codes(df, race_row)
    print(f'  Rounds under "{race_label}": {race_codes}')

    pos_map   = make_map(df, race_row)
    quali_map = make_map(df, quali_row) if quali_row is not None else {}

    # ── Team lookup via stints ──────────────────────────────────────────────
    standings_rows = db['seasons'].get(season_key, {}).get('driver_standings', [])
    driver_stints  = {row['driver']: (row.get('stints') or []) for row in standings_rows}
    driver_team_fb = {row['driver']: row.get('team')            for row in standings_rows}
    for dcode, ddata in db.get('drivers', {}).items():
        if dcode not in driver_team_fb:
            t = ddata.get('seasons', {}).get(season_key, {}).get('team')
            if t:
                driver_team_fb[dcode] = t

    def get_team(driver_id, rnd):
        stints = driver_stints.get(driver_id, [])
        if stints:
            best = None
            for s in stints:
                fr = s.get('from_round', 1)
                tr = s.get('to_round')
                if fr <= rnd and (tr is None or rnd <= tr):
                    if best is None or fr > best.get('from_round', 1):
                        best = s
            if best is not None:
                return best.get('team')
        return driver_team_fb.get(driver_id)

    # ── Build per-race results ──────────────────────────────────────────────
    races_out = []
    for rnd_idx, rcode in enumerate(race_codes):
        round_num    = rnd_idx + 1
        is_sprint    = (rcode in SPRINTS) and not is_f2
        is_f2_sprint = is_f2 and rcode == 'SPR'
        if is_f2_sprint:
            pts_table = F2_SPRINT_PTS
        elif is_sprint:
            pts_table = SPRINT_PTS
        else:
            pts_table = RACE_PTS

        meta    = RACE_META.get(rcode, {})
        entries = []

        for driver_id, pos_vals in pos_map.items():
            if rnd_idx >= len(pos_vals):
                continue
            pos, fl = parse_pos(pos_vals[rnd_idx])
            if pos is None and not fl:
                continue  # did not participate

            # Qualifying position
            q_vals    = quali_map.get(driver_id, [])
            q_raw     = q_vals[rnd_idx] if rnd_idx < len(q_vals) else None
            try:
                quali_pos = int(str(q_raw).strip())
                quali_pos = quali_pos if quali_pos > 0 else None
            except (ValueError, TypeError):
                quali_pos = None

            # Points
            if isinstance(pos, int):
                pts = pts_table.get(pos, 0)
                if fl and not is_sprint and not is_f2 and pos <= 10:
                    pts += 1
            else:
                pts = 0

            entries.append({
                'driver':      driver_id,
                'pos':         pos,
                'team':        get_team(driver_id, round_num),
                'fastest_lap': fl,
                'quali_pos':   quali_pos,
                'points':      pts,
            })

        entries.sort(key=lambda e: e['pos'] if isinstance(e['pos'], int) else 99)

        # Deduplication guard (should never fire with code-based IDs, but kept
        # as a safety net)
        from collections import Counter
        driver_count = Counter(e['driver'] for e in entries)
        duplicates   = {d for d, n in driver_count.items() if n > 1}
        if duplicates:
            for d in sorted(duplicates):
                conflicting = [f"P{e['pos']}" for e in entries if e['driver'] == d]
                print(f'  ERROR: duplicate rows for "{d}" in {rcode}: '
                      f'{conflicting}. BOTH dropped — check the sheet.')
            entries = [e for e in entries if e['driver'] not in duplicates]

        has_results = bool(entries)

        if is_f2:
            race_id = f'{season_key}_{str(round_num).zfill(2)}'
        else:
            race_id = f'{rcode.lower()}_r{round_num}'

        races_out.append({
            'id':      race_id,
            'round':   round_num,
            'name':    rcode,
            'flag':    meta.get('flag', '🏁'),
            'circuit': meta.get('circuit', rcode),
            'date':    season_key.replace('_f2', ''),
            'sprint':  is_sprint or is_f2_sprint,
            'status':  'complete' if has_results else 'upcoming',
            'results': entries,
        })

    return races_out


def update_standings(db, season_key, races_out):
    """Recompute driver and constructor standings from race results in-place."""
    stats = {}
    for race in races_out:
        for e in race['results']:
            d = e['driver']
            if d not in stats:
                stats[d] = {'wins': 0, 'podiums': 0, 'fl': 0, 'poles': 0,
                             'races': 0, 'points': 0, 'finish_counts': {}}
            stats[d]['races']  += 1
            stats[d]['points'] += e['points']
            if isinstance(e['pos'], int):
                if e['pos'] == 1: stats[d]['wins']    += 1
                if e['pos'] <= 3: stats[d]['podiums'] += 1
                fc = stats[d]['finish_counts']
                fc[e['pos']] = fc.get(e['pos'], 0) + 1
            if e['fastest_lap']:        stats[d]['fl']    += 1
            if e.get('quali_pos') == 1: stats[d]['poles'] += 1

    season = db['seasons'][season_key]
    for row in season['driver_standings']:
        s = stats.get(row['driver'], {})
        row.update({
            'wins':         s.get('wins', 0),
            'podiums':      s.get('podiums', 0),
            'fastest_laps': s.get('fl', 0),
            'poles':        s.get('poles', 0),
            'races':        s.get('races', 0),
            'points':       s.get('points', 0),
        })

    def tiebreak_key(row):
        fc = stats.get(row['driver'], {}).get('finish_counts', {})
        return tuple([-row['points']] + [-fc.get(p, 0) for p in range(1, 21)])

    season['driver_standings'].sort(key=tiebreak_key)
    for i, row in enumerate(season['driver_standings']):
        row['pos'] = i + 1

    # Update each driver's top-level team to their most recent completed race
    last_team = {}
    for race in races_out:
        if race['status'] == 'complete':
            for e in race['results']:
                if e.get('team'):
                    last_team[e['driver']] = e['team']
    for row in season['driver_standings']:
        if row['driver'] in last_team:
            row['team'] = last_team[row['driver']]

    # Constructor standings
    team_pts = {}
    for race in races_out:
        for e in race['results']:
            t = e['team']
            if t:
                team_pts[t] = team_pts.get(t, 0) + e['points']

    if any(team_pts.values()):
        season['constructor_standings'] = sorted(
            [{'pos': i + 1, 'team': t, 'points': v, 'wins': 0, 'podiums': 0}
             for i, (t, v) in enumerate(
                 sorted(team_pts.items(), key=lambda x: -x[1]))],
            key=lambda x: x['pos']
        )


# ── Entry point ───────────────────────────────────────────────────────────────

def sync():
    print(f'Fetching sheet (GID {SHEET_GID}) from Google Sheets…')
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(BytesIO(resp.content), encoding='utf-8-sig', header=None)
    print(f'Sheet loaded: {len(df)} rows × {len(df.columns)} columns\n')

    with open(DB_PATH, encoding='utf-8') as f:
        db = json.load(f)

    # ── Driver metadata (codes sheet) ─────────────────────────────────────────
    sync_driver_metadata(db)

    # ── F1 ────────────────────────────────────────────────────────────────────
    print('── F1 ──')
    f1_races = build_races(df, 'F1 Race', 'F1 Quali', F1_SEASON, db, is_f2=False)
    if f1_races:
        update_standings(db, F1_SEASON, f1_races)
        with open(F1_OUT, 'w', encoding='utf-8') as f:
            json.dump({'races': f1_races}, f, indent=2, ensure_ascii=False)
        f1_done = sum(1 for r in f1_races if r['status'] == 'complete')
        print(f'✓ {F1_OUT}: {len(f1_races)} rounds, {f1_done} complete')
        print('  Top 5:')
        for row in db['seasons'][F1_SEASON]['driver_standings'][:5]:
            print(f'    P{row["pos"]} {row["driver"]}: {row["points"]}pts')

    # ── F2 ────────────────────────────────────────────────────────────────────
    print('\n── F2 ──')
    f2_races = build_races(df, 'F2 Race', 'F2 Qualifying', F2_SEASON, db, is_f2=True)
    if f2_races:
        update_standings(db, F2_SEASON, f2_races)
        with open(F2_OUT, 'w', encoding='utf-8') as f:
            json.dump(
                {'year': F2_SEASON, 'series': 'f2', 'races': f2_races},
                f, indent=2, ensure_ascii=False
            )
        f2_done = sum(1 for r in f2_races if r['status'] == 'complete')
        print(f'✓ {F2_OUT}: {len(f2_races)} rounds, {f2_done} complete')
        print('  Top 5:')
        for row in db['seasons'][F2_SEASON]['driver_standings'][:5]:
            print(f'    P{row["pos"]} {row["driver"]}: {row["points"]}pts')

    # ── db.json ───────────────────────────────────────────────────────────────
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print('\n✓ db.json updated')


if __name__ == '__main__':
    sync()

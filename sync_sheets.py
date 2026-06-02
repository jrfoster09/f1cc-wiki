#!/usr/bin/env python3
"""
F1CC Wiki — Sync from Google Sheets
Fetches the live sheet and rebuilds:
  data/races_2026.json      (F1 results)
  data/races_2026_f2.json   (F2 results)
  data/db.json              (standings for both series)

Sheet structure (all on the same tab, GID=224130953):
  Column C label "F1CC"          → F1 finishing positions (cols D onward = races)
  Column C label "QUALIFYING"    → F1 qualifying positions
  Column C label "F2 Race"       → F2 finishing positions
  Column C label "F2 Qualifying" → F2 qualifying positions

Position encoding:
  1       = P1 finish
  1*      = P1 finish with fastest lap
  DNF     = Did Not Finish
  blank/0 = did not participate
"""

import json, os, sys, unicodedata
from io import StringIO, BytesIO

import requests
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
SHEET_ID  = '1XJWNG1R74CADbob6mHo4D3G7DV8gxaQQKTDpHqu2Bqo'
SHEET_GID = '224130953'
CSV_URL   = (
    f'https://docs.google.com/spreadsheets/d/{SHEET_ID}'
    f'/export?format=csv&gid={SHEET_GID}'
)

DATA_DIR  = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH   = os.path.join(DATA_DIR, 'db.json')
F1_OUT    = os.path.join(DATA_DIR, 'races_2026.json')
F2_OUT    = os.path.join(DATA_DIR, 'races_2026_f2.json')

F1_SEASON = '2026'
F2_SEASON = '2026_f2'

RACE_PTS      = {1:25, 2:18, 3:15, 4:12, 5:10, 6:8, 7:6, 8:4, 9:2, 10:1}
SPRINT_PTS    = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}
F2_SPRINT_PTS = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}
SPRINTS       = {'CHNS', 'SAUS', 'AUSS', 'NETS', 'USAS', 'BRAS'}

# Sheet name → db.json slug overrides.
# Add a row here whenever a driver's name in the Google Sheet differs from
# their display name in db.json (e.g. sheet uses ASCII, db uses special chars).
SHEET_NAME_OVERRIDES = {
    'Eetu Vaisanen':      'eetu_vaisanen',
    'Michiii MaraDöner':  'michiii_maradoner',   # sheet uses capital D + ö
    'Michiii MaraDoner':  'michiii_maradoner',   # ASCII variant of above
    'Michiii Maradöner':  'michiii_maradoner',   # lowercase-d variant (db.json spelling)
    'Michiii Maradoner':  'michiii_maradoner',   # ASCII fallback
    'Marek Dubisar':      'marek_dubisar',
}

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
    'AUSS': {'flag': '🇦🇺', 'circuit': 'Albert Park Sprint'},
    'SPR' : {'flag': '🏁', 'circuit': 'Sprint Race'},
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
    'AUT' : {'flag': '🇦🇹', 'circuit': 'Red Bull Ring'},
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def parse_pos(raw):
    """Parse a position cell. Returns (position, fastest_lap_bool)."""
    s = str(raw).strip()
    if s in ('nan', '0', ''):
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


def find_header(df, label):
    """Return the DataFrame row index where column 2 (0-indexed) equals label."""
    for i, row in df.iterrows():
        if str(row.iloc[2]).strip() == label:
            return i
    return None


def make_map(df, start_row, max_drivers=30):
    """Build {driver_name: [col3..col30]} from rows after start_row.

    A single blank name row is skipped (handles merged cells or accidental
    empty rows mid-section). Two consecutive blank name rows = end of section.

    Also stops immediately if a row looks like a new section header (col C
    contains 'F3', 'Reserve', 'RESERVE', 'F3 / Reserve', etc.).  This
    prevents F3/reserve drivers from being accidentally read as F2 entries
    when only a single blank row separates the two sections on the sheet.
    """
    STOP_KEYWORDS = ('F3', 'RESERVE', 'QUALIFYING', 'F1CC', 'F2 RACE', 'F2 QUALIFYING')
    m = {}
    blank_streak = 0
    for i in range(start_row + 1, min(start_row + 1 + max_drivers, len(df))):
        row  = df.iloc[i]
        name = str(row.iloc[2]).strip()
        if not name or name == 'nan':
            blank_streak += 1
            if blank_streak >= 2:
                break   # two blank rows in a row = genuine end of section
            continue    # single blank row = skip and keep reading
        # Stop if this row is a new section header, not a driver name
        name_upper = name.upper()
        if any(kw in name_upper for kw in STOP_KEYWORDS):
            print(f'  make_map: stopping at section header "{name}"')
            break
        blank_streak = 0
        m[name] = [str(row.iloc[c]).strip() for c in range(3, 31)]
    return m


# ── Core builder ──────────────────────────────────────────────────────────────

def build_races(df, main_label, quali_label, season_key, db, is_f2=False, name_to_id=None):
    """
    Parse one series' results from the sheet.
    Returns a list of race dicts ready for the JSON file.
    name_to_id: dict mapping display name → driver slug key in db.json
    """
    main_row = find_header(df, main_label)
    if main_row is None:
        print(f'  WARNING: "{main_label}" header not found — skipping {season_key}')
        return []

    quali_row = find_header(df, quali_label)

    # Race codes from the header row (cols D onward)
    raw_codes = [str(df.iloc[main_row, c]).strip() for c in range(3, 31)]
    race_codes = [r for r in raw_codes if r not in ('nan', 'TOTAL', '')]
    print(f'  Rounds found under "{main_label}": {race_codes}')

    pos_map   = make_map(df, main_row)
    quali_map = make_map(df, quali_row) if quali_row is not None else {}

    # Per-round team lookup via stints (supports mid-season driver moves)
    standings_rows = db['seasons'].get(season_key, {}).get('driver_standings', [])
    driver_stints  = {row['driver']: (row.get('stints') or []) for row in standings_rows}
    driver_team_fb = {row['driver']: row.get('team') for row in standings_rows}
    # Fallback: drivers dict for anyone not yet in standings
    for dname, ddata in db.get('drivers', {}).items():
        if dname not in driver_team_fb:
            t = ddata.get('seasons', {}).get(season_key, {}).get('team')
            if t:
                driver_team_fb[dname] = t

    def get_team(driver_id, rnd):
        """Return team for driver_id at round rnd, honouring stints."""
        stints = driver_stints.get(driver_id, [])
        if stints:
            best = None
            for s in stints:
                fr = s.get('from_round', 1)
                tr = s.get('to_round')   # None/absent = open-ended
                if fr <= rnd and (tr is None or rnd <= tr):
                    if best is None or fr > best.get('from_round', 1):
                        best = s
            if best is not None:
                return best.get('team')
        return driver_team_fb.get(driver_id)

    races_out = []
    round_num = 0
    for rnd_idx, rcode in enumerate(race_codes):
        round_num += 1   # increment first so get_team uses the correct round
        is_sprint    = (rcode in SPRINTS) and not is_f2
        is_f2_sprint = is_f2 and rcode == 'SPR'
        if is_f2_sprint:
            pts_table = F2_SPRINT_PTS
        elif is_sprint:
            pts_table = SPRINT_PTS
        else:
            pts_table = RACE_PTS
        meta      = RACE_META.get(rcode, {})
        entries   = []

        for driver, pos_vals in pos_map.items():
            if rnd_idx >= len(pos_vals):
                continue
            pos, fl = parse_pos(pos_vals[rnd_idx])
            if pos is None and not fl:
                continue  # did not participate

            # Resolve display name → db slug key (handles Väisänen, Maradöner, etc.)
            driver_id = name_to_id.get(driver, driver) if name_to_id else driver

            # Qualifying position
            q_vals    = quali_map.get(driver, [])
            q_raw     = q_vals[rnd_idx] if rnd_idx < len(q_vals) else None
            try:
                quali_pos = int(str(q_raw).strip())
                quali_pos = quali_pos if quali_pos > 0 else None
            except (ValueError, TypeError):
                quali_pos = None

            # Points
            if isinstance(pos, int):
                pts = pts_table.get(pos, 0)
                # Fastest-lap +1: F1 feature races only (not sprints, not F2)
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
        has_results = bool(entries)

        # Race ID — sequential round_num so there are never gaps
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
                # Count every finish position for tiebreaking (most wins → most P2s → ...)
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
        """Sort key: points desc, then most P1s, then most P2s, ..., most P20s."""
        fc = stats.get(row['driver'], {}).get('finish_counts', {})
        return tuple([-row['points']] + [-fc.get(p, 0) for p in range(1, 21)])

    season['driver_standings'].sort(key=tiebreak_key)
    for i, row in enumerate(season['driver_standings']):
        row['pos'] = i + 1

    # Update each driver's top-level team to their most recent completed race team,
    # so the standings table always shows the current assignment after a team change.
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
    print(f'Fetching sheet from Google Sheets (GID {SHEET_GID})…')
    resp = requests.get(CSV_URL, timeout=30)
    resp.raise_for_status()
    # Pass raw bytes to pandas with utf-8-sig encoding.
    # 'utf-8-sig' handles both plain UTF-8 and UTF-8-with-BOM (which Google
    # Sheets sometimes adds), and avoids requests' Latin-1 default for text/csv.
    df = pd.read_csv(BytesIO(resp.content), encoding='utf-8-sig')
    print(f'Sheet loaded: {len(df)} rows × {len(df.columns)} columns\n')

    with open(DB_PATH, encoding='utf-8') as f:
        db = json.load(f)

    # Build display-name → driver slug reverse map so sheet names like
    # "Eetu Väisänen" resolve to db.json keys like "eetu_vaisanen"
    name_to_id = {v.get('name', k): k for k, v in db.get('drivers', {}).items()}
    name_to_id.update({k: k for k in db.get('drivers', {})})  # slug → slug too
    # Apply manual overrides for sheet names that use ASCII spellings
    name_to_id.update(SHEET_NAME_OVERRIDES)
    # Auto-add ASCII-normalized variants of every display name so the lookup
    # works whether the Google Sheet uses "Eetu Väisänen" (special chars) or
    # "Eetu Vaisanen" (plain ASCII). Both will now resolve to "eetu_vaisanen".
    for display_name, slug in list(name_to_id.items()):
        ascii_name = (unicodedata.normalize('NFKD', display_name)
                      .encode('ASCII', 'ignore').decode('ASCII'))
        if ascii_name != display_name:
            name_to_id.setdefault(ascii_name, slug)

    # ── F1 ────────────────────────────────────────────────────────────────────
    print('── F1 ──')
    f1_races = build_races(df, 'F1CC', 'QUALIFYING', F1_SEASON, db, is_f2=False, name_to_id=name_to_id)
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
    f2_races = build_races(df, 'F2 Race', 'F2 Qualifying', F2_SEASON, db, is_f2=True, name_to_id=name_to_id)
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

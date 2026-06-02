#!/usr/bin/env python3
"""
F1CC Wiki — Local CSV builder for 2026 season
Reads data/csv/F1CC_2026.csv (a local export of the 26_data Google Sheet tab)
and rebuilds data/races_2026.json + data/db.json standings.

Expected CSV layout (matches the 26_data tab, GID 359936286):
  Section headers in col A: "F1 Quali", "F1 Race", "F2 Qualifying", "F2 Race"
  Driver rows: Nation(A), Code(B), Name(C), results(D+)
  Driver Code (col B) is the canonical ID — e.g. ev_69, rk_99

Position encoding:
  7    = P7 finish
  7*   = P7 with fastest lap
  DNF  = Did Not Finish (0 points)
  NC   = Not Classified / Not Competing (skip)
  blank/0 = did not participate (skip)
"""

import json, os, re, sys
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR  = os.path.join(os.path.dirname(__file__), 'data')
CSV_PATH  = os.path.join(DATA_DIR, 'csv', 'F1CC_2026.csv')
DB_PATH   = os.path.join(DATA_DIR, 'db.json')
F1_OUT    = os.path.join(DATA_DIR, 'races_2026.json')
F2_OUT    = os.path.join(DATA_DIR, 'races_2026_f2.json')

F1_SEASON = '2026'
F2_SEASON = '2026_f2'

RACE_PTS      = {1:25, 2:18, 3:15, 4:12, 5:10, 6:8, 7:6, 8:4, 9:2, 10:1}
SPRINT_PTS    = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}
F2_SPRINT_PTS = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}
SPRINTS       = {'CHNS', 'SAUS', 'AUTS', 'NETS', 'USAS', 'BRAS'}

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


def parse_pos(raw):
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
    for i, row in df.iterrows():
        if str(row.iloc[0]).strip() == label:
            return i
    return None


def get_race_codes(df, section_row):
    for r in [section_row, section_row + 1]:
        if r >= len(df):
            continue
        codes = [str(df.iloc[r, c]).strip() for c in range(3, df.shape[1])]
        codes = [c for c in codes if c not in ('', 'nan', 'TOTAL')]
        if codes:
            return codes
    return []


def make_map(df, section_row, max_rows=30):
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
            continue
        m[code] = [str(row.iloc[c]).strip() for c in range(3, df.shape[1])]
    return m


def build():
    if not os.path.exists(CSV_PATH):
        print(f'ERROR: CSV not found at {CSV_PATH}')
        sys.exit(1)

    df = pd.read_csv(CSV_PATH, encoding='utf-8', header=None)
    print(f'CSV loaded: {len(df)} rows\n')

    with open(DB_PATH, encoding='utf-8') as f:
        db = json.load(f)

    # ── F1 ────────────────────────────────────────────────────────────────────
    print('── F1 ──')
    race_row  = find_section(df, 'F1 Race')
    quali_row = find_section(df, 'F1 Quali')
    if race_row is None:
        print('ERROR: "F1 Race" section not found in CSV')
        sys.exit(1)

    race_codes = get_race_codes(df, race_row)
    print(f'Rounds: {race_codes}')

    pos_map   = make_map(df, race_row)
    quali_map = make_map(df, quali_row) if quali_row is not None else {}
    print(f'Drivers: {list(pos_map.keys())}')

    standings_rows = db['seasons'][F1_SEASON].get('driver_standings', [])
    driver_stints  = {r['driver']: (r.get('stints') or []) for r in standings_rows}
    driver_team_fb = {r['driver']: r.get('team')           for r in standings_rows}

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

    races_out = []
    for rnd_idx, rcode in enumerate(race_codes):
        round_num = rnd_idx + 1
        is_sprint = rcode in SPRINTS
        pts_table = SPRINT_PTS if is_sprint else RACE_PTS
        meta      = RACE_META.get(rcode, {})
        entries   = []

        for driver_id, pos_vals in pos_map.items():
            if rnd_idx >= len(pos_vals):
                continue
            pos, fl = parse_pos(pos_vals[rnd_idx])
            if pos is None and not fl:
                continue

            q_vals    = quali_map.get(driver_id, [])
            q_raw     = q_vals[rnd_idx] if rnd_idx < len(q_vals) else None
            try:
                quali_pos = int(str(q_raw).strip())
                quali_pos = quali_pos if quali_pos > 0 else None
            except (ValueError, TypeError):
                quali_pos = None

            if isinstance(pos, int):
                pts = pts_table.get(pos, 0)
                if fl and not is_sprint and pos <= 10:
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

        from collections import Counter
        dupes = {d for d, n in Counter(e['driver'] for e in entries).items() if n > 1}
        if dupes:
            for d in sorted(dupes):
                print(f'  WARNING: duplicate "{d}" in {rcode} — both dropped')
            entries = [e for e in entries if e['driver'] not in dupes]

        races_out.append({
            'id':      f'{rcode.lower()}_r{round_num}',
            'round':   round_num,
            'name':    rcode,
            'flag':    meta.get('flag', '🏁'),
            'circuit': meta.get('circuit', rcode),
            'date':    '2026',
            'sprint':  is_sprint,
            'status':  'complete' if entries else 'upcoming',
            'results': entries,
        })

    # Standings
    stats = {}
    for race in races_out:
        for e in race['results']:
            d = e['driver']
            if d not in stats:
                stats[d] = {'wins':0,'podiums':0,'fl':0,'poles':0,'races':0,
                             'points':0,'finish_counts':{}}
            stats[d]['races']  += 1
            stats[d]['points'] += e['points']
            if isinstance(e['pos'], int):
                if e['pos'] == 1: stats[d]['wins']    += 1
                if e['pos'] <= 3: stats[d]['podiums'] += 1
                fc = stats[d]['finish_counts']
                fc[e['pos']] = fc.get(e['pos'], 0) + 1
            if e['fastest_lap']:        stats[d]['fl']    += 1
            if e.get('quali_pos') == 1: stats[d]['poles'] += 1

    s26 = db['seasons'][F1_SEASON]
    for row in s26['driver_standings']:
        s = stats.get(row['driver'], {})
        row.update({'wins': s.get('wins',0), 'podiums': s.get('podiums',0),
                    'fastest_laps': s.get('fl',0), 'poles': s.get('poles',0),
                    'races': s.get('races',0), 'points': s.get('points',0)})

    def tiebreak_key(row):
        fc = stats.get(row['driver'], {}).get('finish_counts', {})
        return tuple([-row['points']] + [-fc.get(p, 0) for p in range(1, 21)])

    s26['driver_standings'].sort(key=tiebreak_key)
    for i, row in enumerate(s26['driver_standings']):
        row['pos'] = i + 1

    team_pts = {}
    for race in races_out:
        for e in race['results']:
            if e['team']:
                team_pts[e['team']] = team_pts.get(e['team'], 0) + e['points']
    if any(team_pts.values()):
        s26['constructor_standings'] = sorted(
            [{'pos':i+1,'team':t,'points':v,'wins':0,'podiums':0}
             for i,(t,v) in enumerate(sorted(team_pts.items(),key=lambda x:-x[1]))],
            key=lambda x: x['pos']
        )

    with open(F1_OUT, 'w', encoding='utf-8') as f:
        json.dump({'races': races_out}, f, indent=2, ensure_ascii=False)
    complete = sum(1 for r in races_out if r['status'] == 'complete')
    print(f'✓ races_2026.json: {len(races_out)} races, {complete} complete')

    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f'✓ db.json updated')
    print(f'\nTop 5:')
    for row in s26['driver_standings'][:5]:
        print(f'  P{row["pos"]} {row["driver"]}: {row["points"]}pts')


if __name__ == '__main__':
    build()

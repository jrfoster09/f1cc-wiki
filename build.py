#!/usr/bin/env python3
"""
F1CC Wiki — Automated JSON builder for 2026 season
Reads data/csv/F1CC_2026.csv and rebuilds races_2026.json + db.json standings.

CSV Structure (2026 format):
  Row 0-19:   Points gained table (IGNORE)
  Row 25:     "QUALIFYING" header
  Row 26-45:  Qualifying positions per driver per race (cols 3-30)
  Row 51:     "F1CC" header + race codes (cols 3-30)
  Row 52-71:  Race finishing positions per driver (cols 3-30)

Fastest lap: add * after position e.g. "1*" means P1 with fastest lap
"""

import json, os, re, sys
import pandas as pd

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR  = os.path.join(os.path.dirname(__file__), 'data')
CSV_PATH  = os.path.join(DATA_DIR, 'csv', 'F1CC_2026.csv')
DB_PATH   = os.path.join(DATA_DIR, 'db.json')
OUT_PATH  = os.path.join(DATA_DIR, 'races_2026.json')

RACE_PTS   = {1:25, 2:18, 3:15, 4:12, 5:10, 6:8, 7:6, 8:4, 9:2, 10:1}
SPRINT_PTS = {1:8,  2:7,  3:6,  4:5,  5:4,  6:3, 7:2, 8:1}
SPRINTS    = {'CHNS','SAUS','AUSS','NETS','USAS','BRAS'}

RACE_META = {
    'AUS' :{'flag':'🇦🇺','circuit':'Albert Park'},
    'CHNS':{'flag':'🇨🇳','circuit':'Shanghai Sprint'},
    'CHN' :{'flag':'🇨🇳','circuit':'Shanghai'},
    'JPN' :{'flag':'🇯🇵','circuit':'Suzuka'},
    'BAH' :{'flag':'🇧🇭','circuit':'Bahrain International'},
    'SAUS':{'flag':'🇸🇦','circuit':'Jeddah Sprint'},
    'SAU' :{'flag':'🇸🇦','circuit':'Jeddah Street'},
    'MIA' :{'flag':'🇺🇸','circuit':'Miami International'},
    'CAN' :{'flag':'🇨🇦','circuit':'Circuit Gilles Villeneuve'},
    'MON' :{'flag':'🇲🇨','circuit':'Monaco'},
    'SPA' :{'flag':'🇪🇸','circuit':'Circuit de Barcelona'},
    'AUSS':{'flag':'🇦🇺','circuit':'Albert Park Sprint'},
    'BRI' :{'flag':'🇬🇧','circuit':'Silverstone'},
    'BEL' :{'flag':'🇧🇪','circuit':'Spa-Francorchamps'},
    'HUN' :{'flag':'🇭🇺','circuit':'Hungaroring'},
    'NETS':{'flag':'🇳🇱','circuit':'Zandvoort Sprint'},
    'NET' :{'flag':'🇳🇱','circuit':'Zandvoort'},
    'ITA' :{'flag':'🇮🇹','circuit':'Monza'},
    'AZE' :{'flag':'🇦🇿','circuit':'Baku'},
    'SIN' :{'flag':'🇸🇬','circuit':'Marina Bay'},
    'USAS':{'flag':'🇺🇸','circuit':'COTA Sprint'},
    'USA' :{'flag':'🇺🇸','circuit':'Circuit of the Americas'},
    'MEX' :{'flag':'🇲🇽','circuit':'Hermanos Rodriguez'},
    'BRAS':{'flag':'🇧🇷','circuit':'Interlagos Sprint'},
    'BRA' :{'flag':'🇧🇷','circuit':'Interlagos'},
    'LVG' :{'flag':'🇺🇸','circuit':'Las Vegas Street'},
    'ABU' :{'flag':'🇦🇪','circuit':'Yas Marina'},
}

def parse_pos(raw):
    s = str(raw).strip()
    if s in ('nan', '0', ''):
        return None, False
    fl = s.endswith('*')
    s = s.rstrip('*').strip()
    if s.upper() in ('DNF', 'DSQ', 'RET'):
        return s.upper(), fl
    try:
        v = int(s)
        return (v if v > 0 else None), fl
    except ValueError:
        return None, False

def build():
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: CSV not found at {CSV_PATH}")
        sys.exit(1)

    df = pd.read_csv(CSV_PATH, encoding='utf-8')

    # ── Race codes from the F1CC header row (row 51, cols 3-30) ───────────────
    f1cc_header_row = None
    for i, row in df.iterrows():
        if str(row.iloc[2]).strip() == 'F1CC':
            f1cc_header_row = i
            break
    if f1cc_header_row is None:
        print("ERROR: Could not find 'F1CC' header row in CSV")
        sys.exit(1)

    races_raw = [str(df.iloc[f1cc_header_row, c]).strip()
                 for c in range(3, 31)]
    races = [r for r in races_raw if r not in ('nan', 'TOTAL', '')]
    print(f"Races found: {races}")

    # ── Results rows (immediately after F1CC header) ──────────────────────────
    results_start = f1cc_header_row + 1
    results_end   = results_start + 21  # max 20 drivers + buffer

    # ── Qualifying rows (after QUALIFYING header, row 25 area) ───────────────
    quali_header_row = None
    for i, row in df.iterrows():
        if str(row.iloc[2]).strip() == 'QUALIFYING':
            quali_header_row = i
            break
    quali_start = (quali_header_row + 1) if quali_header_row is not None else None

    # ── Build lookup maps ─────────────────────────────────────────────────────
    def make_map(start, end):
        m = {}
        for i in range(start, min(end, len(df))):
            row = df.iloc[i]
            name = str(row.iloc[2]).strip()
            if not name or name == 'nan':
                break
            m[name] = [str(row.iloc[c]).strip() for c in range(3, 31)]
        return m

    pos_map   = make_map(results_start, results_end)
    quali_map = make_map(quali_start, quali_start + 21) if quali_start else {}

    print(f"Drivers in results: {list(pos_map.keys())}")

    # ── Load db.json to get team assignments ──────────────────────────────────
    with open(DB_PATH, encoding='utf-8') as f:
        db = json.load(f)

    # Build display-name → driver slug reverse map so CSV names like
    # "Eetu Väisänen" resolve to db.json keys like "eetu_vaisanen"
    name_to_id = {v.get('name', k): k for k, v in db.get('drivers', {}).items()}
    name_to_id.update({k: k for k in db.get('drivers', {})})  # slug → slug too

    # Build driver→team map from 2026 driver_standings stints (keyed by slug)
    driver_team = {}
    for row in db['seasons']['2026']['driver_standings']:
        driver_team[row['driver']] = row.get('team')

    # ── Build race results ────────────────────────────────────────────────────
    races_out = []
    for rnd_idx, rcode in enumerate(races):
        is_sprint = rcode in SPRINTS
        pts_table = SPRINT_PTS if is_sprint else RACE_PTS
        meta      = RACE_META.get(rcode, {})
        entries   = []

        for driver, pos_vals in pos_map.items():
            if rnd_idx >= len(pos_vals):
                continue
            pos, fl = parse_pos(pos_vals[rnd_idx])
            if pos is None and not fl:
                continue  # not entered

            # Resolve display name → db slug key (handles Väisänen, Maradöner, etc.)
            driver_id = name_to_id.get(driver, driver)

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
                if fl and not is_sprint and pos <= 10:
                    pts += 1
            else:
                pts = 0

            entries.append({
                'driver':      driver_id,
                'pos':         pos,
                'team':        driver_team.get(driver_id),
                'fastest_lap': fl,
                'quali_pos':   quali_pos,
                'points':      pts,
            })

        entries.sort(key=lambda e: e['pos'] if isinstance(e['pos'], int) else 99)
        has_results = bool(entries)

        races_out.append({
            'round':   rnd_idx + 1,
            'id':      f"{rcode.lower()}_r{rnd_idx+1}",
            'name':    rcode,
            'flag':    meta.get('flag', '🏁'),
            'circuit': meta.get('circuit', rcode),
            'date':    '2026',
            'sprint':  is_sprint,
            'status':  'complete' if has_results else 'upcoming',
            'results': entries,
        })

    # ── Update db.json standings ──────────────────────────────────────────────
    stats = {}
    for race in races_out:
        for e in race['results']:
            d = e['driver']
            if d not in stats:
                stats[d] = {'wins':0,'podiums':0,'fl':0,'poles':0,'races':0,'points':0,'finish_counts':{}}
            stats[d]['races']  += 1
            stats[d]['points'] += e['points']
            if isinstance(e['pos'], int):
                if e['pos'] == 1: stats[d]['wins']    += 1
                if e['pos'] <= 3: stats[d]['podiums']  += 1
                fc = stats[d]['finish_counts']
                fc[e['pos']] = fc.get(e['pos'], 0) + 1
            if e['fastest_lap']:          stats[d]['fl']    += 1
            if e.get('quali_pos') == 1:   stats[d]['poles'] += 1

    s26 = db['seasons']['2026']
    for row in s26['driver_standings']:
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

    s26['driver_standings'].sort(key=tiebreak_key)
    for i, row in enumerate(s26['driver_standings']):
        row['pos'] = i + 1

    # Constructor standings
    team_pts = {}
    for race in races_out:
        for e in race['results']:
            t = e['team']
            if t:
                team_pts[t] = team_pts.get(t, 0) + e['points']

    if any(team_pts.values()):  # only update if there are actual points
        s26['constructor_standings'] = sorted(
            [{'team':t,'points':v,'wins':0,'podiums':0,'pos':i+1}
             for i,(t,v) in enumerate(sorted(team_pts.items(), key=lambda x:-x[1]))],
            key=lambda x: x['pos']
        )

    # ── Write outputs ─────────────────────────────────────────────────────────
    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump({'races': races_out}, f, indent=2, ensure_ascii=False)
    complete = sum(1 for r in races_out if r['status'] == 'complete')
    print(f"✓ races_2026.json: {len(races_out)} races, {complete} complete")

    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, indent=2, ensure_ascii=False)
    print(f"✓ db.json: standings updated")
    print(f"\nTop 5 standings:")
    for row in s26['driver_standings'][:5]:
        print(f"  P{row['pos']} {row['driver']}: {row['points']}pts")

if __name__ == '__main__':
    build()
    import elo
    elo.run()

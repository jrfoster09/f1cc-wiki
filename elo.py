#!/usr/bin/env python3
"""
F1CC ELO Engine
===============
Reads all race JSON files, db.json, and WCC_History.csv.
Calculates driver ELO ratings for F1 and F2 pools separately.
Outputs data/elo.json.

Processing order (chronological so ELO chains correctly):
  1. 2024 F1
  2. 2025 F1
  3. 2025 F2        ← separate pool; must complete before graduation check
  4. F2→F1 graduation conversion for 2026 F1 entrants
  5. 2026 F1
  6. 2026 F2        ← continues F2 pool from 2025
"""

import csv
import json
import os
from collections import defaultdict
from datetime import date

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH  = os.path.join(DATA_DIR, 'db.json')
WCC_CSV  = os.path.join(DATA_DIR, 'csv', 'WCC_History.csv')
OUT_PATH = os.path.join(DATA_DIR, 'elo.json')

K_RACE       = 20
K_SPRINT     = 10
K_QUALI      = 10
STARTING_ELO = 1500.0
MIN_RACES    = 2    # minimum races to appear in rankings


# ── Data loaders ──────────────────────────────────────────────────────────────

def load_db():
    with open(DB_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_races(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f'  (skipping {filename} — not found)')
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f).get('races', [])


def load_wcc_history():
    """
    Returns {(season_int, round_int): {team_id: wcc_pos_int}}.
    Falls back to empty dict (neutral P5 for all teams) if CSV missing.

    Parses the actual sheet export format, which is section-based:
      Row: "2024,WCC Standings,..."   → start of 2024 section
      Row: "Round,RBR,FER,MCL,..."   → team column headers (abbreviations)
      Row: "2,3,1,4,5,..."           → round 2 WCC positions

    Team abbreviations → db.json IDs:
      RBR=red_bull, FER=ferrari, MCL=mclaren, MER=mercedes,
      AST=aston_martin, ALP=alpine, WIL=williams, VCA=vcarb,
      AUD=audi, HAA=haas

    Rows where all values are 1 are skipped (placeholder data).
    Only the left-hand standings table is read (first 12 columns).
    """
    ABBREV = {
        'RBR': 'red_bull',  'FER': 'ferrari',       'MCL': 'mclaren',
        'MER': 'mercedes',  'AST': 'aston_martin',   'ALP': 'alpine',
        'WIL': 'williams',  'VCA': 'vcarb',          'AUD': 'audi',
        'HAA': 'haas',
    }

    wcc = {}
    if not os.path.exists(WCC_CSV):
        print(f'  WARNING: {WCC_CSV} not found — car adjustments disabled (neutral P5 used)')
        return wcc

    current_season = None
    team_cols      = []   # [(col_index, team_id), ...]

    with open(WCC_CSV, encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            first = row[0].strip()

            # Year header row — first cell is a 4-digit year
            if first.isdigit() and len(first) == 4:
                current_season = int(first)
                team_cols      = []
                continue

            # Column header row — first cell is "Round"
            if first == 'Round':
                team_cols = [
                    (i, ABBREV[c.strip()])
                    for i, c in enumerate(row[:12])   # only left-hand table
                    if c.strip() in ABBREV
                ]
                continue

            # Data row — first cell is a round number
            if current_season and first.isdigit():
                rnd   = int(first)
                entry = {}
                for col, team_id in team_cols:
                    if col < len(row) and row[col].strip():
                        try:
                            entry[team_id] = int(row[col].strip())
                        except ValueError:
                            pass

                # Skip empty rows and placeholder rows (all 1s = not yet filled)
                if entry and not all(v == 1 for v in entry.values()):
                    wcc[(current_season, rnd)] = entry

    rounds_found = {s: sum(1 for (se, _) in wcc if se == s) for s in {s for s, _ in wcc}}
    for yr, cnt in sorted(rounds_found.items()):
        print(f'  WCC {yr}: {cnt} rounds loaded')
    return wcc


# ── ELO helpers ───────────────────────────────────────────────────────────────

def expected_score(ra, rb):
    """Standard ELO expected score for player A against player B."""
    return 1.0 / (1.0 + 10.0 ** ((rb - ra) / 400.0))


def car_adjustment(wcc_pos):
    """
    Returns a raw adjustment value based on constructor championship position.
    Top cars penalised (expected to score well), backmarkers rewarded.
    Divided by 20 before use to normalise to the 0-1 field_score scale.
    """
    adj = {1: -3, 2: -3, 3: -2, 4: -2, 5: -1, 6: -1, 7: 0, 8: 0, 9: 1, 10: 1}
    return adj.get(wcc_pos, 0)


def get_wcc_pos(team_id, season, round_num, wcc_history):
    """
    Returns WCC position for a team at a specific round.
    Uses the nearest earlier round if exact match not found.
    Defaults to neutral P5 if no data available at all.
    """
    key = (season, round_num)
    if key not in wcc_history:
        available = [r for (s, r) in wcc_history if s == season and r <= round_num]
        if not available:
            return 5
        key = (season, max(available))
    return wcc_history[key].get(team_id, 5)


def is_dnf(pos):
    """Any non-integer finish position (DNF, DNFM, DNFD, DNFN, RET, DSQ, etc.)
    All DNFs are treated the same: last place + flat penalty."""
    return pos is not None and not isinstance(pos, int)


def effective_pos(pos, total_drivers):
    """
    Returns (effective_position, is_neutral).
    - Normal finish: (pos, False)
    - Any DNF/RET:   (total_drivers, False) — last place, always counted
    """
    if isinstance(pos, int) and pos > 0:
        return pos, False
    if is_dnf(pos):
        return total_drivers, False
    return None, True  # pos is None — did not participate


# ── ELO State ─────────────────────────────────────────────────────────────────

class EloState:
    """Holds all ELO data for one pool (F1 or F2)."""

    def __init__(self, pool_name='F1'):
        self.pool        = pool_name
        self.elo         = {}   # driver → current ELO (float)
        self.starting    = {}   # driver → starting ELO (1500 or grad ELO)
        self.peak        = {}   # driver → all-time peak ELO
        self.races       = {}   # driver → total race entries counted
        self.breakdown   = {}   # driver → {component: cumulative delta}
        self.history     = {}   # driver → [{season, round, race, ...}, ...]
        self.season_snap = {}   # driver → {season_str: elo_at_end_of_season}

    # ── Initialisation ────────────────────────────────────────────────────────

    def _init(self, driver):
        """Lazy-initialise a driver at 1500 on first encounter."""
        if driver not in self.elo:
            self.elo[driver]       = STARTING_ELO
            self.starting[driver]  = STARTING_ELO
            self.peak[driver]      = STARTING_ELO
            self.races[driver]     = 0
            self.breakdown[driver] = dict(
                teammate_race=0.0, field_race=0.0,
                teammate_quali=0.0, field_quali=0.0,
                dnf_penalties=0.0,
            )
            self.history[driver]   = []
            self.season_snap[driver] = {}

    def get_elo(self, driver):
        self._init(driver)
        return self.elo[driver]

    def set_starting_elo(self, driver, elo):
        """Override starting ELO — used for F2 graduates entering F1."""
        self._init(driver)          # ensure all fields exist
        self.elo[driver]      = elo
        self.starting[driver] = elo
        self.peak[driver]     = max(self.peak[driver], elo)

    # ── Updates ───────────────────────────────────────────────────────────────

    def apply(self, driver, component, delta):
        """Apply a delta to one ELO component."""
        self._init(driver)
        self.elo[driver]                  += delta
        self.breakdown[driver][component] += delta
        self.peak[driver] = max(self.peak[driver], self.elo[driver])

    def record(self, driver, season, rnd, name, event_type, pre_elo, total_delta):
        """Log one race entry to history and increment race counter."""
        self._init(driver)
        self.races[driver] += 1
        self.history[driver].append({
            'season':     season,
            'round':      rnd,
            'race':       name,
            'event_type': event_type,
            'elo_before': round(pre_elo, 1),
            'elo_after':  round(self.elo[driver], 1),
            'delta':      round(total_delta, 2),
        })

    def snapshot_season(self, driver, season):
        """Record each driver's ELO at the end of a season."""
        self._init(driver)
        self.season_snap[driver][str(season)] = round(self.elo[driver], 1)

    # ── Rankings output ───────────────────────────────────────────────────────

    def to_rankings(self, min_races=MIN_RACES):
        """
        Returns sorted list of driver ranking dicts.
        Sorted by ELO-per-race (descending). Filters to min_races.
        """
        rows = []
        for driver, elo in self.elo.items():
            n = self.races.get(driver, 0)
            if n < min_races:
                continue
            start    = self.starting.get(driver, STARTING_ELO)
            change   = elo - start
            per_race = change / n if n else 0.0
            rows.append({
                'pos':              0,       # filled after sort
                'driver':           driver,
                'current_elo':      round(elo, 1),
                'starting_elo':     round(start, 1),
                'elo_change':       round(change, 1),
                'total_races':      n,
                'elo_per_race':     round(per_race, 3),
                'peak_elo':         round(self.peak.get(driver, elo), 1),
                'breakdown':        {k: round(v, 1) for k, v in
                                     self.breakdown.get(driver, {}).items()},
                'season_snapshots': self.season_snap.get(driver, {}),
                'history':          self.history.get(driver, []),
            })
        rows.sort(key=lambda x: -x['elo_per_race'])
        for i, row in enumerate(rows):
            row['pos'] = i + 1
        return rows


# ── Core race processor ───────────────────────────────────────────────────────

def process_race(race, season, season_key, db, wcc_history, state):
    """
    Process one race or sprint entry and update ELO state.

    All deltas are computed using pre-race ELOs (snapshot before any
    changes are applied) so teammate calculations are symmetric and
    independent of loop order.
    """
    if race.get('status') != 'complete':
        return
    results = race.get('results', [])
    if not results:
        return

    rnd       = race['round']
    name      = race['name']
    is_sprint = race.get('sprint', False)
    K_r       = K_SPRINT if is_sprint else K_RACE
    N         = len(results)
    if N <= 1:
        return  # can't compute field score or teammate battle with one driver

    event_type = 'SPRINT' if is_sprint else 'RACE'

    # Snapshot ELOs before any changes so all calculations use the same baseline
    pre_elo = {e['driver']: state.get_elo(e['driver']) for e in results}

    # Group entries by team for teammate lookup
    by_team = defaultdict(list)
    for e in results:
        t = e.get('team')
        if t:
            by_team[t].append(e)

    # ── Calculate all deltas (no state mutation yet) ───────────────────────────
    all_comp_deltas = {}   # driver → {component: delta}

    for e in results:
        driver = e['driver']
        pos    = e['pos']
        q_pos  = e.get('quali_pos')
        team   = e.get('team')

        d_elo = pre_elo[driver]
        eff, neutral = effective_pos(pos, N)

        comps = defaultdict(float)

        # 1. DNF flat penalty (-5 ELO for any non-finish)
        if is_dnf(pos):
            comps['dnf_penalties'] += -5.0

        # 2. Field performance — race
        #    P1 = score 1.0, last place = 0.0, neutral expectation = 0.5
        #    Car adjustment normalised to same scale (/ 20)
        if not neutral:
            wcc_pos = get_wcc_pos(team, season, rnd, wcc_history) if team else 5
            adj     = car_adjustment(wcc_pos) / 20.0
            fs      = (N - eff) / (N - 1)
            comps['field_race'] += K_r * 0.25 * (fs - 0.5 + adj)

        # 3. Field performance — qualifying
        if isinstance(q_pos, int) and q_pos > 0:
            qs = (N - q_pos) / (N - 1)
            comps['field_quali'] += K_QUALI * 0.15 * (qs - 0.5)

        # 4 & 5. Teammate battles (race and quali)
        if team and by_team[team]:
            mates = [m for m in by_team[team] if m['driver'] != driver]
            if mates:
                mate  = mates[0]   # take first teammate (edge case: 3+ per team)
                m_elo = pre_elo.get(mate['driver'], STARTING_ELO)
                m_pos = mate['pos']
                m_q   = mate.get('quali_pos')

                # 4. Teammate race battle
                if not neutral:
                    m_eff, m_neutral = effective_pos(m_pos, N)
                    if not m_neutral:
                        score = 1.0 if eff < m_eff else 0.0
                        exp   = expected_score(d_elo, m_elo)
                        comps['teammate_race'] += K_r * 0.35 * (score - exp)

                # 5. Teammate quali battle
                #    Skipped if either driver's quali position is missing
                if (isinstance(q_pos, int) and q_pos > 0 and
                        isinstance(m_q, int) and m_q > 0):
                    score = 1.0 if q_pos < m_q else 0.0
                    exp   = expected_score(d_elo, m_elo)
                    comps['teammate_quali'] += K_QUALI * 0.25 * (score - exp)

        all_comp_deltas[driver] = dict(comps)

    # ── Apply all deltas atomically ────────────────────────────────────────────
    for driver, comps in all_comp_deltas.items():
        total = sum(comps.values())
        for component, delta in comps.items():
            state.apply(driver, component, delta)
        state.record(driver, season, rnd, name, event_type,
                     pre_elo[driver], total)


# ── Main entry point ──────────────────────────────────────────────────────────

def run():
    print('── ELO Engine ──────────────────────────────────────────')
    print('Loading data...')
    db          = load_db()
    wcc_history = load_wcc_history()

    f1 = EloState('F1')
    f2 = EloState('F2')

    # ── 2024 F1 ───────────────────────────────────────────────────────────────
    print('\n[2024 F1]')
    for race in load_races('races_2024.json'):
        process_race(race, 2024, '2024', db, wcc_history, f1)
    for d in list(f1.elo):
        f1.snapshot_season(d, 2024)
    complete_24 = sum(1 for r in load_races('races_2024.json') if r.get('status') == 'complete')
    print(f'  {len(f1.elo)} drivers  |  {complete_24} rounds processed')

    # ── 2025 F1 ───────────────────────────────────────────────────────────────
    print('\n[2025 F1]')
    for race in load_races('races_2025.json'):
        process_race(race, 2025, '2025', db, wcc_history, f1)
    for d in list(f1.elo):
        f1.snapshot_season(d, 2025)
    complete_25 = sum(1 for r in load_races('races_2025.json') if r.get('status') == 'complete')
    print(f'  {len(f1.elo)} drivers tracked  |  {complete_25} rounds processed')

    # ── 2025 F2 ───────────────────────────────────────────────────────────────
    print('\n[2025 F2]')
    for race in load_races('races_2025_f2.json'):
        process_race(race, 2025, '2025_f2', db, wcc_history, f2)
    for d in list(f2.elo):
        f2.snapshot_season(d, 2025)
    print(f'  {len(f2.elo)} F2 drivers tracked')

    # ── F2 Season Regression: 2025 → 2026 ────────────────────────────────────
    # Shrinks each driver's ELO deviation by 50% toward 1500 before 2026 begins.
    # Prevents 2025 veterans being permanently buried below new 2026 drivers who
    # start fresh at 1500. New 2026 entrants are unaffected (not yet initialised).
    print('\n[F2 Season Regression: 2025 → 2026]')
    for driver in list(f2.elo):
        old_elo = f2.elo[driver]
        new_elo = round(1500.0 + (old_elo - 1500.0) * 0.5, 1)
        f2.elo[driver] = new_elo
        f2.peak[driver] = max(f2.peak.get(driver, new_elo), new_elo)
    print(f'  Regressed {len(f2.elo)} drivers toward 1500 (50% factor)')

    # ── F2 → F1 Graduation (into 2026 F1) ────────────────────────────────────
    print('\n[Graduation check: F2 2025 → F1 2026]')

    # Collect all 2026 F1 drivers from both completed results and standings
    f1_2026 = set()
    for race in load_races('races_2026.json'):
        for e in race.get('results', []):
            f1_2026.add(e['driver'])
    for row in db.get('seasons', {}).get('2026', {}).get('driver_standings', []):
        f1_2026.add(row['driver'])

    f1_veterans = set(f1.elo.keys())   # already competed in F1 before 2026
    f2_alumni   = set(f2.elo.keys())   # competed in F2 2025

    graduates = (f1_2026 & f2_alumni) - f1_veterans
    if graduates:
        for grad in sorted(graduates):
            f2_final = f2.elo.get(grad, STARTING_ELO)
            bonus    = (f2_final - STARTING_ELO) * 0.20
            f1_start = round(STARTING_ELO + bonus, 1)
            f1.set_starting_elo(grad, f1_start)
            print(f'  {grad}: F2 ELO {f2_final:.1f} → F1 start {f1_start:.1f}')
    else:
        print('  No F2→F1 graduates found')

    # ── 2026 F1 ───────────────────────────────────────────────────────────────
    print('\n[2026 F1]')
    for race in load_races('races_2026.json'):
        process_race(race, 2026, '2026', db, wcc_history, f1)
    for d in list(f1.elo):
        f1.snapshot_season(d, 2026)
    complete_26 = sum(1 for r in load_races('races_2026.json') if r.get('status') == 'complete')
    print(f'  {len(f1.elo)} drivers tracked  |  {complete_26} rounds processed so far')

    # ── 2026 F2 ───────────────────────────────────────────────────────────────
    print('\n[2026 F2]')
    for race in load_races('races_2026_f2.json'):
        process_race(race, 2026, '2026_f2', db, wcc_history, f2)
    for d in list(f2.elo):
        f2.snapshot_season(d, 2026)
    print(f'  {len(f2.elo)} F2 drivers tracked')

    # ── Build output ──────────────────────────────────────────────────────────
    print('\nBuilding elo.json...')
    output = {
        'last_updated': str(date.today()),
        'f1': {'rankings': f1.to_rankings()},
        'f2': {'rankings': f2.to_rankings()},
    }

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    f1r = output['f1']['rankings']
    f2r = output['f2']['rankings']
    print(f'✓ elo.json written')
    print(f'  F1: {len(f1r)} ranked (of {len(f1.elo)} total drivers, min {MIN_RACES} races)')
    print(f'  F2: {len(f2r)} ranked (of {len(f2.elo)} total F2 drivers)')
    if f1r:
        top = f1r[0]
        print(f'\n  F1 #1  {top["driver"]}')
        print(f'         ELO {top["current_elo"]:.1f}  '
              f'({top["elo_per_race"]:+.3f}/race over {top["total_races"]} races)')
    if f2r:
        top2 = f2r[0]
        print(f'  F2 #1  {top2["driver"]}')
        print(f'         ELO {top2["current_elo"]:.1f}  '
              f'({top2["elo_per_race"]:+.3f}/race over {top2["total_races"]} races)')
    print('────────────────────────────────────────────────────────')


if __name__ == '__main__':
    run()

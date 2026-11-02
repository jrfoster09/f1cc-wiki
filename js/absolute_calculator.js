/**
 * F1CC Wiki - Absolute Data Live Engine
 * Computes all 35 alternative championship tables dynamically from official race results (races_2026.json, races_2026_f2.json, db.json).
 * Curated & Designed by Eren Aygen
 */

(function(global) {
  'use strict';

  function computeAllAbsoluteData(racesF1, racesF2, db) {
    if (!racesF1 || !racesF1.races) return null;

    const drivers = (db && db.drivers) ? db.drivers : {};
    const f1Races = (racesF1.races || []).filter(r => r.status === 'complete' && r.results && r.results.length > 0);
    const f2Races = (racesF2 && racesF2.races)
      ? racesF2.races.filter(r => r.status === 'complete' && r.results && r.results.length > 0)
      : [];

    const streetKeywords = ['monaco', 'baku', 'singapore', 'marina bay', 'jeddah', 'las vegas', 'miami', 'albert park'];
    const isStreet = (circuit, name) => {
      const s = ((circuit || '') + ' ' + (name || '')).toLowerCase();
      return streetKeywords.some(k => s.includes(k));
    };

    const f1DriverSet = new Set();
    f1Races.forEach(race => race.results.forEach(r => { if (r.driver) f1DriverSet.add(r.driver); }));
    const f2DriverSet = new Set();
    f2Races.forEach(race => race.results.forEach(r => { if (r.driver) f2DriverSet.add(r.driver); }));

    // Standard scales
    const F1_SCALE = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1];
    const SPRINT_SCALE = [8, 7, 6, 5, 4, 3, 2, 1];
    const MOTOGP_SCALE = [25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1];
    const MARIO_SCALE = [15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1];
    const HISTORIC_0308_SCALE = [10, 8, 6, 5, 4, 3, 2, 1];
    const NASCAR_SCALE = [40, 35, 34, 33, 32, 31, 30, 29, 28, 27, 26, 25, 24, 23, 22, 21, 20, 19, 18, 17, 16];
    const INDYCAR_SCALE = [50, 40, 35, 32, 30, 28, 26, 24, 22, 20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5];
    const FE_SCALE = [25, 18, 15, 12, 10, 8, 6, 4, 2, 1];

    const getDriverInfo = (dId) => {
      const d = drivers[dId] || {};
      return {
        driver_id: dId,
        driver_name: d.name || dId,
        nat: d.country || '',
        flag: d.flag_emoji || '🏁'
      };
    };

    // 1. Real Championship Baseline
    const realScores = {};
    f1DriverSet.forEach(d => { realScores[d] = { points: 0, wins: 0, podiums: 0 }; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        if (!realScores[d]) realScores[d] = { points: 0, wins: 0, podiums: 0 };
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          if (race.sprint) {
            if (pos <= SPRINT_SCALE.length) realScores[d].points += SPRINT_SCALE[pos - 1];
          } else {
            if (pos <= F1_SCALE.length) {
              let pts = F1_SCALE[pos - 1];
              if (race.double_points) pts *= 2;
              realScores[d].points += pts;
            }
            if (pos === 1) realScores[d].wins += 1;
            if (pos <= 3) realScores[d].podiums += 1;
          }
          if (r.fastest_lap && pos <= 10) realScores[d].points += 1;
        }
      });
    });

    const sortedReal = Object.entries(realScores)
      .sort((a,b) => b[1].points - a[1].points || b[1].wins - a[1].wins || b[1].podiums - a[1].podiums);
    const realRanks = {};
    sortedReal.forEach(([dId], idx) => { realRanks[dId] = idx + 1; });

    const getDeltaBadge = (dId, currentRank) => {
      const baseRank = realRanks[dId];
      if (!baseRank) return '—';
      const diff = baseRank - currentRank;
      if (diff > 0) return `▲${diff}`;
      if (diff < 0) return `▼${Math.abs(diff)}`;
      return '-';
    };

    const formatTable = (tableId, category, series, title, desc, sortedList, opts = {}) => {
      const standings = sortedList.map(([dId, data], idx) => {
        const dInfo = getDriverInfo(dId);
        const pos = idx + 1;
        const ptsVal = typeof data === 'object' && data !== null ? data.points : data;
        const delta = opts.noDelta ? '—' : getDeltaBadge(dId, pos);
        return {
          pos,
          ...dInfo,
          points: String(ptsVal),
          delta,
          extra: (typeof data === 'object' && data.extra) ? data.extra : {}
        };
      });

      const out = {
        id: tableId,
        category,
        series,
        title,
        desc,
        type: opts.type || 'pts_delta',
        standings
      };
      if (opts.logo) out.logo = opts.logo;
      return out;
    };

    const tables = [];

    // Real
    tables.push(formatTable(
      'real', 'performance', 'f1', 'Real Championship',
      'Standard official F1CC championship standings with wins, podiums, and official points.',
      sortedReal.map(([dId, d]) => [dId, { points: d.points, extra: { wins: String(d.wins), podiums: String(d.podiums) } }]),
      { type: 'real', noDelta: true }
    ));

    // Quali
    const qualiScores = {};
    f1DriverSet.forEach(d => { qualiScores[d] = { points: 0, poles: 0 }; });
    f1Races.forEach(race => {
      if (!race.sprint) {
        race.results.forEach(r => {
          const d = r.driver;
          const q = r.quali_pos;
          if (typeof q === 'number' && q >= 1) {
            if (q <= F1_SCALE.length) qualiScores[d].points += F1_SCALE[q - 1];
            if (q === 1) qualiScores[d].poles += 1;
          }
        });
      }
    });
    const sortedQuali = Object.entries(qualiScores).sort((a,b) => b[1].points - a[1].points || b[1].poles - a[1].poles);
    tables.push(formatTable(
      'quali', 'performance', 'f1', 'Qualifying Championship',
      'Championship standings based purely on qualifying positions and pole positions across the season.',
      sortedQuali.map(([dId, d]) => [dId, { points: d.points, extra: { poles: String(d.poles) } }]),
      { type: 'quali' }
    ));

    // Combined Quali + Race
    const combinedScores = {};
    f1DriverSet.forEach(d => {
      combinedScores[d] = (realScores[d]?.points || 0) + (qualiScores[d]?.points || 0);
    });
    tables.push(formatTable(
      'combined_quali_race', 'performance', 'f1', 'Combined Quali + Race Championship',
      'Overall points combining qualifying championship points and race championship points.',
      Object.entries(combinedScores).sort((a,b) => b[1] - a[1])
    ));

    // Position Gain/Loss
    const posGainScores = {};
    f1DriverSet.forEach(d => { posGainScores[d] = { net: 0, dnf: 0 }; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const q = r.quali_pos;
        const pos = r.pos;
        if (typeof pos === 'number' && typeof q === 'number') {
          posGainScores[d].net += (q - pos);
        } else {
          posGainScores[d].dnf += 1;
        }
      });
    });
    tables.push(formatTable(
      'pos_gain_loss', 'positions', 'f1', 'Position Gain/Loss (+/-) Championship',
      'Net positions gained or lost from starting grid position to final finish position across all races.',
      Object.entries(posGainScores).sort((a,b) => b[1].net - a[1].net)
        .map(([dId, d]) => [dId, { points: d.net, extra: { dnf: String(d.dnf) } }]),
      { type: 'dnf_pts' }
    ));

    // Just Gained
    const justGainedScores = {};
    f1DriverSet.forEach(d => { justGainedScores[d] = { gained: 0, dnf: 0 }; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const q = r.quali_pos;
        const pos = r.pos;
        if (typeof pos === 'number' && typeof q === 'number') {
          const delta = q - pos;
          if (delta > 0) justGainedScores[d].gained += delta;
        } else {
          justGainedScores[d].dnf += 1;
        }
      });
    });
    tables.push(formatTable(
      'just_gained', 'positions', 'f1', 'Positions Just Gained Championship',
      'Only positions gained during races (ignoring positions lost) across the season.',
      Object.entries(justGainedScores).sort((a,b) => b[1].gained - a[1].gained)
        .map(([dId, d]) => [dId, { points: d.gained, extra: { dnf: String(d.dnf) } }]),
      { type: 'dnf_pts' }
    ));

    // Sprint Championship
    const sprintScores = {};
    f1DriverSet.forEach(d => { sprintScores[d] = { points: 0, wins: 0 }; });
    f1Races.forEach(race => {
      if (race.sprint) {
        race.results.forEach(r => {
          const d = r.driver;
          const pos = r.pos;
          if (typeof pos === 'number' && pos >= 1 && pos <= SPRINT_SCALE.length) {
            sprintScores[d].points += SPRINT_SCALE[pos - 1];
            if (pos === 1) sprintScores[d].wins += 1;
          }
        });
      }
    });
    tables.push(formatTable(
      'sprint', 'formats', 'f1', 'Sprint Championship',
      'Points scored exclusively in official Sprint races throughout the season.',
      Object.entries(sprintScores).sort((a,b) => b[1].points - a[1].points || b[1].wins - a[1].wins)
        .map(([dId, d]) => [dId, { points: d.points, extra: d.wins > 0 ? { wins: String(d.wins) } : {} }]),
      { type: 'sprint' }
    ));

    // Main Race Championship
    const mainScores = {};
    f1DriverSet.forEach(d => { mainScores[d] = { points: 0, wins: 0 }; });
    f1Races.forEach(race => {
      if (!race.sprint) {
        race.results.forEach(r => {
          const d = r.driver;
          const pos = r.pos;
          if (typeof pos === 'number' && pos >= 1 && pos <= F1_SCALE.length) {
            let pts = F1_SCALE[pos - 1];
            if (race.double_points) pts *= 2;
            mainScores[d].points += pts;
            if (pos === 1) mainScores[d].wins += 1;
          }
          if (r.fastest_lap && typeof pos === 'number' && pos <= 10) mainScores[d].points += 1;
        });
      }
    });
    tables.push(formatTable(
      'main_race', 'formats', 'f1', 'Main Race (Grand Prix) Championship',
      'Points scored exclusively in Main Sunday Grand Prix races (Sprint points excluded).',
      Object.entries(mainScores).sort((a,b) => b[1].points - a[1].points || b[1].wins - a[1].wins)
        .map(([dId, d]) => [dId, { points: d.points, extra: d.wins > 0 ? { wins: String(d.wins) } : {} }])
    ));

    // Street Tracks
    const streetScores = {};
    f1DriverSet.forEach(d => { streetScores[d] = 0; });
    f1Races.forEach(race => {
      if (isStreet(race.circuit, race.name)) {
        race.results.forEach(r => {
          const d = r.driver;
          const pos = r.pos;
          if (typeof pos === 'number' && pos >= 1) {
            if (race.sprint && pos <= SPRINT_SCALE.length) {
              streetScores[d] += SPRINT_SCALE[pos - 1];
            } else if (!race.sprint && pos <= F1_SCALE.length) {
              streetScores[d] += F1_SCALE[pos - 1];
            }
            if (r.fastest_lap && pos <= 10) streetScores[d] += 1;
          }
        });
      }
    });
    tables.push(formatTable(
      'street_tracks', 'formats', 'f1', 'Street Tracks Championship',
      'Points accumulated exclusively on street circuits (Monaco, Baku, Singapore, Jeddah, Las Vegas, etc.).',
      Object.entries(streetScores).sort((a,b) => b[1] - a[1])
    ));

    // Average Positions
    const avgScores = {};
    f1DriverSet.forEach(d => { avgScores[d] = { qualiSum: 0, qualiCount: 0, finishSum: 0, finishCount: 0 }; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        if (typeof r.quali_pos === 'number') {
          avgScores[d].qualiSum += r.quali_pos;
          avgScores[d].qualiCount += 1;
        }
        if (typeof r.pos === 'number') {
          avgScores[d].finishSum += r.pos;
          avgScores[d].finishCount += 1;
        }
      });
    });
    const avgDataList = Object.entries(avgScores).map(([dId, d]) => {
      const aq = d.qualiCount > 0 ? (d.qualiSum / d.qualiCount) : 0;
      const af = d.finishCount > 0 ? (d.finishSum / d.finishCount) : 0;
      const delta = (aq - af);
      const deltaStr = (delta >= 0 ? '' : '') + delta.toFixed(1).replace('.', ',');
      return [dId, {
        points: deltaStr,
        numericDelta: delta,
        extra: {
          avg_quali: 'P' + aq.toFixed(1).replace('.', ','),
          avg_finish: 'P' + af.toFixed(1).replace('.', ',')
        }
      }];
    });
    avgDataList.sort((a,b) => b[1].numericDelta - a[1].numericDelta);
    tables.push(formatTable(
      'avg_positions', 'positions', 'f1', 'Average Positions (Quali vs Finish)',
      'Average qualifying position (AQ), average finish position (AF), and average delta.',
      avgDataList,
      { type: 'avg_pos', noDelta: true }
    ));

    // Reverse Championship
    const reverseScores = {};
    f1DriverSet.forEach(d => { reverseScores[d] = { points: 0, wins: 0, podiums: 0 }; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= 21) {
          const invRank = Math.max(1, 22 - pos);
          const pts = invRank <= F1_SCALE.length ? F1_SCALE[invRank - 1] : 1;
          reverseScores[d].points += pts;
          if (pos >= 20) reverseScores[d].wins += 1;
          if (pos >= 18) reverseScores[d].podiums += 1;
        }
      });
    });
    tables.push(formatTable(
      'reverse', 'formats', 'f1', 'Reverse Championship',
      'Inverted point system awarding maximum points to lower finishing positions.',
      Object.entries(reverseScores).sort((a,b) => b[1].points - a[1].points)
        .map(([dId, d]) => [dId, { points: d.points, extra: { wins: String(d.wins), podiums: String(d.podiums) } }]),
      { type: 'reverse' }
    ));

    // NASCCAR Point System
    const nascarScores = {};
    f1DriverSet.forEach(d => { nascarScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          const pts = pos <= NASCAR_SCALE.length ? NASCAR_SCALE[pos - 1] : 1;
          nascarScores[d] += pts;
        }
      });
    });
    tables.push(formatTable(
      'nascar', 'alt_points', 'f1', 'NASCCAR Point System',
      'Championship calculated using NASCAR Cup Series scoring rules.',
      Object.entries(nascarScores).sort((a,b) => b[1] - a[1]),
      { logo: 'assets/logos/nascar.png' }
    ));

    // MotoGP
    const motogpScores = {};
    f1DriverSet.forEach(d => { motogpScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= MOTOGP_SCALE.length) {
          motogpScores[d] += MOTOGP_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatTable(
      'motogp', 'alt_points', 'f1', 'MotoGP Point System',
      'Championship calculated using the official MotoGP scoring system (25, 20, 16, 13, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1).',
      Object.entries(motogpScores).sort((a,b) => b[1] - a[1])
    ));

    // Every Position (Race)
    const everyRaceScores = {};
    f1DriverSet.forEach(d => { everyRaceScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= 22) {
          everyRaceScores[d] += Math.max(1, 23 - pos);
        }
      });
    });
    tables.push(formatTable(
      'every_pos_race', 'extreme', 'f1', 'Every Position Point Championship (Race)',
      'Points awarded for every single finishing position without cutoff.',
      Object.entries(everyRaceScores).sort((a,b) => b[1] - a[1])
    ));

    // Every Position (Quali)
    const everyQualiScores = {};
    f1DriverSet.forEach(d => { everyQualiScores[d] = 0; });
    f1Races.forEach(race => {
      if (!race.sprint) {
        race.results.forEach(r => {
          const d = r.driver;
          const q = r.quali_pos;
          if (typeof q === 'number' && q >= 1 && q <= 22) {
            everyQualiScores[d] += Math.max(1, 23 - q);
          }
        });
      }
    });
    tables.push(formatTable(
      'every_pos_quali', 'extreme', 'f1', 'Every Position Point Championship (Quali)',
      'Points awarded for every qualifying position without cutoff.',
      Object.entries(everyQualiScores).sort((a,b) => b[1] - a[1])
    ));

    // Combined Position
    const combinedPosScores = {};
    f1DriverSet.forEach(d => {
      combinedPosScores[d] = (everyRaceScores[d] || 0) + (everyQualiScores[d] || 0);
    });
    tables.push(formatTable(
      'combined_pos', 'extreme', 'f1', 'Combined Position Championship',
      'Combined points across both qualifying and race for all positions.',
      Object.entries(combinedPosScores).sort((a,b) => b[1] - a[1])
    ));

    // Le Mans / WEC
    const lemansScores = {};
    f1DriverSet.forEach(d => { lemansScores[d] = 0; });
    f1Races.forEach(race => {
      const isEndurance = race.double_points || ['silverstone', 'spa', 'yas marina'].some(c => (race.circuit||'').toLowerCase().includes(c));
      const mult = isEndurance ? 2 : 1;
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= F1_SCALE.length) {
          lemansScores[d] += (F1_SCALE[pos - 1] * mult);
        }
      });
    });
    tables.push(formatTable(
      'lemans', 'alt_points', 'f1', '24H Le Mans / WEC Point System',
      'Championship calculated using FIA World Endurance Championship (WEC/Le Mans) scoring.',
      Object.entries(lemansScores).sort((a,b) => b[1] - a[1])
    ));

    // Mario Kart
    const marioScores = {};
    f1DriverSet.forEach(d => { marioScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= MARIO_SCALE.length) {
          marioScores[d] += MARIO_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatTable(
      'mario', 'alt_points', 'f1', 'Mario Kart Point System',
      'Championship calculated using classic Mario Kart scoring rules (15, 12, 10, 8, 7, 6, 5, 4, 3, 2, 1).',
      Object.entries(marioScores).sort((a,b) => b[1] - a[1])
    ));

    // Classic 2003–2008 F1
    const f103Scores = {};
    f1DriverSet.forEach(d => { f103Scores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= HISTORIC_0308_SCALE.length) {
          f103Scores[d] += HISTORIC_0308_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatTable(
      'f1_2003_2008', 'alt_points', 'f1', 'Classic 2003–2008 F1 Point System',
      'Historic Formula 1 points system (10-8-6-5-4-3-2-1 for top 8).',
      Object.entries(f103Scores).sort((a,b) => b[1] - a[1])
    ));

    // F2 System in F1
    const f2InF1Scores = {};
    f1DriverSet.forEach(d => { f2InF1Scores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          if (race.sprint) {
            const S8 = [10, 8, 6, 5, 4, 3, 2, 1];
            if (pos <= S8.length) f2InF1Scores[d] += S8[pos - 1];
          } else {
            if (pos <= F1_SCALE.length) f2InF1Scores[d] += F1_SCALE[pos - 1];
            if (r.quali_pos === 1) f2InF1Scores[d] += 2;
          }
          if (r.fastest_lap && pos <= 10) f2InF1Scores[d] += 1;
        }
      });
    });
    tables.push(formatTable(
      'f2_system_in_f1', 'alt_points', 'f1', 'F2 Point System in F1',
      'Formula 2 scoring rules (25 for Feature win, 10 for Sprint win, pole & fastest lap points) applied to F1.',
      Object.entries(f2InF1Scores).sort((a,b) => b[1] - a[1])
    ));

    // IndyCar
    const indycarScores = {};
    f1DriverSet.forEach(d => { indycarScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          const pts = pos <= INDYCAR_SCALE.length ? INDYCAR_SCALE[pos - 1] : 5;
          indycarScores[d] += pts;
          if (r.quali_pos === 1) indycarScores[d] += 1;
        }
      });
    });
    tables.push(formatTable(
      'indycar', 'alt_points', 'f1', 'F1CC IndyCar Series Point System',
      'Championship calculated using NTT IndyCar Series scoring system.',
      Object.entries(indycarScores).sort((a,b) => b[1] - a[1]),
      { logo: 'assets/logos/indycar.png' }
    ));

    // Formula E
    const feScores = {};
    f1DriverSet.forEach(d => { feScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          if (pos <= FE_SCALE.length) feScores[d] += FE_SCALE[pos - 1];
          if (r.quali_pos === 1) feScores[d] += 3;
          if (r.fastest_lap && pos <= 10) feScores[d] += 1;
        }
      });
    });
    tables.push(formatTable(
      'formula_e', 'alt_points', 'f1', 'Formula E (n4x World Championship) Point System',
      'Championship calculated with official Formula E scoring (25-18-15-12-10-8-6-4-2-1, 3 pts for Pole, 1 pt for Fastest Lap).',
      Object.entries(feScores).sort((a,b) => b[1] - a[1]),
      { logo: 'assets/logos/formula_e.png' }
    ));

    // PGC
    const pgcScores = {};
    f1DriverSet.forEach(d => { pgcScores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const q = r.quali_pos;
        const pos = r.pos;
        if (typeof q === 'number') {
          if (q <= 5) pgcScores[d] += (6 - q) * 2;
          if (typeof pos === 'number' && q <= 3 && pos <= 3) pgcScores[d] += 5;
        }
      });
    });
    tables.push(formatTable(
      'pgc', 'performance', 'f1', 'PGC (Pole-to-Grid Championship)',
      'Special championship tracking qualifying conversion, pole performances and front-row execution.',
      Object.entries(pgcScores).sort((a,b) => b[1] - a[1])
    ));

    // 50-to-1
    const s50Scores = {};
    f1DriverSet.forEach(d => { s50Scores[d] = 0; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= 50) {
          s50Scores[d] += (51 - pos);
        }
      });
    });
    tables.push(formatTable(
      'system_50_1', 'alt_points', 'f1', '50-to-1 Point System',
      'Linear championship awarding 50 points to winner down to 1 point.',
      Object.entries(s50Scores).sort((a,b) => b[1] - a[1])
    ));

    // Multiply
    const multScores = {};
    f1DriverSet.forEach(d => { multScores[d] = 1; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= 10) {
          multScores[d] *= F1_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatTable(
      'multiply', 'extreme', 'f1', 'Multiply Championship (Points Multiplied)',
      'Championship calculated by multiplying points earned in top 10 finishes.',
      Object.entries(multScores).sort((a,b) => b[1] - a[1])
        .map(([dId, v]) => [dId, v.toExponential(3).replace('e+', 'E+')])
    ));

    // Inverse Multiply
    const invMultScores = {};
    f1DriverSet.forEach(d => { invMultScores[d] = 1; });
    f1Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          invMultScores[d] *= (pos / 5);
        }
      });
    });
    tables.push(formatTable(
      'inverse_multiply', 'extreme', 'f1', 'Inverse / Fractional Multiply Championship',
      'Points multiplied with inverted position weighting (highlighting consistent midfield and backmarker finishes).',
      Object.entries(invMultScores).sort((a,b) => b[1] - a[1])
        .map(([dId, v]) => [dId, v > 1000 ? v.toFixed(0) : v.toFixed(4).replace('.', ',')])
    ));

    // F2 Section
    const f2RealScores = {};
    f2DriverSet.forEach(d => { f2RealScores[d] = { points: 0, wins: 0 }; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1) {
          if (race.sprint) {
            const S8 = [10, 8, 6, 5, 4, 3, 2, 1];
            if (pos <= S8.length) f2RealScores[d].points += S8[pos - 1];
          } else {
            if (pos <= F1_SCALE.length) f2RealScores[d].points += F1_SCALE[pos - 1];
            if (r.quali_pos === 1) f2RealScores[d].points += 2;
          }
          if (pos === 1) f2RealScores[d].wins += 1;
          if (r.fastest_lap && pos <= 10) f2RealScores[d].points += 1;
        }
      });
    });
    const sortedF2Real = Object.entries(f2RealScores).sort((a,b) => b[1].points - a[1].points || b[1].wins - a[1].wins);
    const f2RealRanks = {};
    sortedF2Real.forEach(([dId], idx) => { f2RealRanks[dId] = idx + 1; });

    const getF2Delta = (dId, rank) => {
      const base = f2RealRanks[dId];
      if (!base) return '—';
      const diff = base - rank;
      if (diff > 0) return `▲${diff}`;
      if (diff < 0) return `▼${Math.abs(diff)}`;
      return '-';
    };

    const formatF2Table = (tableId, title, desc, sortedList, opts = {}) => {
      const standings = sortedList.map(([dId, data], idx) => {
        const dInfo = getDriverInfo(dId);
        const pos = idx + 1;
        const ptsVal = typeof data === 'object' && data !== null ? data.points : data;
        const delta = opts.noDelta ? '—' : getF2Delta(dId, pos);
        return {
          pos,
          ...dInfo,
          points: String(ptsVal),
          delta,
          extra: (typeof data === 'object' && data.extra) ? data.extra : {}
        };
      });
      return {
        id: tableId,
        category: 'f2',
        series: 'f2',
        title,
        desc,
        type: opts.type || 'pts_delta',
        standings
      };
    };

    // F2CC F1 System
    const f2F1Scores = {};
    f2DriverSet.forEach(d => { f2F1Scores[d] = 0; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= F1_SCALE.length) {
          f2F1Scores[d] += F1_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatF2Table(
      'f2cc_f1_sys', 'F2CC (F1 System)',
      'Formula 2 championship recalculated using official Formula 1 points rules (25-18-15...).',
      Object.entries(f2F1Scores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Official System
    tables.push(formatF2Table(
      'f2cc_f2_sys', 'F2CC (Official F2 System)',
      'Formula 2 championship standings under official F2 scoring.',
      sortedF2Real.map(([dId, d]) => [dId, d.points]),
      { noDelta: true }
    ));

    // F2CC Quali
    const f2QualiScores = {};
    f2DriverSet.forEach(d => { f2QualiScores[d] = 0; });
    f2Races.forEach(race => {
      if (!race.sprint) {
        race.results.forEach(r => {
          const d = r.driver;
          const q = r.quali_pos;
          if (typeof q === 'number' && q >= 1 && q <= F1_SCALE.length) {
            f2QualiScores[d] += F1_SCALE[q - 1];
          }
        });
      }
    });
    tables.push(formatF2Table(
      'f2cc_quali', 'F2CC Qualifying Championship',
      'Formula 2 standings based exclusively on qualifying results.',
      Object.entries(f2QualiScores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Every Race 25p
    const f2Every25Scores = {};
    f2DriverSet.forEach(d => { f2Every25Scores[d] = 0; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= F1_SCALE.length) {
          f2Every25Scores[d] += F1_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatF2Table(
      'f2cc_every_25p', 'F2CC Every Race 25p System',
      'Formula 2 standings awarding full 25 points to winners of both Sprint and Feature races.',
      Object.entries(f2Every25Scores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Every Race 10p
    const f2Every10Scores = {};
    f2DriverSet.forEach(d => { f2Every10Scores[d] = 0; });
    const S8 = [10, 8, 6, 5, 4, 3, 2, 1];
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= S8.length) {
          f2Every10Scores[d] += S8[pos - 1];
        }
      });
    });
    tables.push(formatF2Table(
      'f2cc_every_10p', 'F2CC Every Race 10p System',
      'Formula 2 standings with 10-point winner scaling across all races.',
      Object.entries(f2Every10Scores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Moto2
    const f2MotoScores = {};
    f2DriverSet.forEach(d => { f2MotoScores[d] = 0; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        const pos = r.pos;
        if (typeof pos === 'number' && pos >= 1 && pos <= MOTOGP_SCALE.length) {
          f2MotoScores[d] += MOTOGP_SCALE[pos - 1];
        }
      });
    });
    tables.push(formatF2Table(
      'f2cc_moto2', 'F2CC (Moto2 System)',
      'Moto2 points scoring scale applied across all Formula 2 races.',
      Object.entries(f2MotoScores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Position Gain / Loss
    const f2PosGainScores = {};
    f2DriverSet.forEach(d => { f2PosGainScores[d] = 0; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        if (typeof r.pos === 'number' && typeof r.quali_pos === 'number') {
          f2PosGainScores[d] += (r.quali_pos - r.pos);
        }
      });
    });
    tables.push(formatF2Table(
      'f2cc_pos_gain_loss', 'F2CC Position Gain / Loss (+/-)',
      'Total net positions gained or lost from grid to chequered flag in Formula 2.',
      Object.entries(f2PosGainScores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Just Gained
    const f2JustGainScores = {};
    f2DriverSet.forEach(d => { f2JustGainScores[d] = 0; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        if (typeof r.pos === 'number' && typeof r.quali_pos === 'number') {
          const delta = r.quali_pos - r.pos;
          if (delta > 0) f2JustGainScores[d] += delta;
        }
      });
    });
    tables.push(formatF2Table(
      'f2cc_just_gain', 'F2CC Positions Just Gained',
      'Total overtakes / forward positions gained across all Formula 2 races.',
      Object.entries(f2JustGainScores).sort((a,b) => b[1] - a[1])
    ));

    // F2CC Avg Quali
    const f2AvgQualiScores = {};
    f2DriverSet.forEach(d => { f2AvgQualiScores[d] = { sum: 0, count: 0 }; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        if (typeof r.quali_pos === 'number') {
          f2AvgQualiScores[d].sum += r.quali_pos;
          f2AvgQualiScores[d].count += 1;
        }
      });
    });
    const f2AvgQualiList = Object.entries(f2AvgQualiScores)
      .filter(([_, d]) => d.count > 0)
      .map(([dId, d]) => {
        const avg = d.sum / d.count;
        return [dId, { points: 'P' + avg.toFixed(1).replace('.', ','), avgNum: avg }];
      });
    f2AvgQualiList.sort((a,b) => a[1].avgNum - b[1].avgNum);
    tables.push(formatF2Table(
      'f2cc_avg_quali', 'F2CC Average Qualifying Position',
      'Average starting grid / qualifying position across the season (lower is better).',
      f2AvgQualiList,
      { noDelta: true }
    ));

    // F2CC Avg Race
    const f2AvgRaceScores = {};
    f2DriverSet.forEach(d => { f2AvgRaceScores[d] = { sum: 0, count: 0 }; });
    f2Races.forEach(race => {
      race.results.forEach(r => {
        const d = r.driver;
        if (typeof r.pos === 'number') {
          f2AvgRaceScores[d].sum += r.pos;
          f2AvgRaceScores[d].count += 1;
        }
      });
    });
    const f2AvgRaceList = Object.entries(f2AvgRaceScores)
      .filter(([_, d]) => d.count > 0)
      .map(([dId, d]) => {
        const avg = d.sum / d.count;
        return [dId, { points: 'P' + avg.toFixed(1).replace('.', ','), avgNum: avg }];
      });
    f2AvgRaceList.sort((a,b) => a[1].avgNum - b[1].avgNum);
    tables.push(formatF2Table(
      'f2cc_avg_race', 'F2CC Average Finish Position',
      'Average classified finish position in Formula 2 (lower is better).',
      f2AvgRaceList,
      { noDelta: true }
    ));

    return {
      meta: {
        title: 'Absolute Data',
        season: '2026',
        author: 'Eren Aygen',
        description: 'Advanced alternative points systems, qualifying championships, position delta analytics, and custom performance metrics computed 100% live from official race results.'
      },
      categories: [
        { id: 'all', name: 'All Tables', count: tables.length },
        { id: 'performance', name: 'Quali & Performance', desc: 'Qualifying, Real Championship, Combined standings and PGC' },
        { id: 'formats', name: 'Formats & Tracks', desc: 'Sprint, Grand Prix, Street tracks and Reverse championships' },
        { id: 'positions', name: 'Overtakes & Deltas', desc: 'Position gains, losses and average grid vs finish metrics' },
        { id: 'alt_points', name: 'Alternative Point Systems', desc: 'NASCAR, MotoGP, Le Mans, Mario Kart, IndyCar, Formula E and historic scales' },
        { id: 'f2', name: 'F2 Analytics', desc: 'Formula 2 alternative points, qualifying, and delta standings' },
        { id: 'extreme', name: 'Extreme & Multipliers', desc: 'Multiply championships, inverse scales, and every-position points' }
      ],
      tables
    };
  }

  // Export to window/module
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { computeAllAbsoluteData };
  }
  if (typeof global !== 'undefined') {
    global.computeAllAbsoluteData = computeAllAbsoluteData;
  }
})(typeof window !== 'undefined' ? window : this);

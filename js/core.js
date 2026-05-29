// ── F1CC Core JS ──
// Loads db.json and exposes helpers used by all pages.

let DB = null;

async function loadDB() {
  if (DB) return DB;
  const resp = await fetch('../data/db.json');
  DB = await resp.json();
  return DB;
}

// Call from index.html (same dir as data/)
async function loadDBRoot() {
  if (DB) return DB;
  const resp = await fetch('data/db.json');
  DB = await resp.json();
  return DB;
}

function getTeamStyle(teamId, teams) {
  const t = teams[teamId];
  if (!t) return '';
  const hex = t.color;
  const r = parseInt(hex.slice(1,3),16);
  const g = parseInt(hex.slice(3,5),16);
  const b = parseInt(hex.slice(5,7),16);
  return `background:rgba(${r},${g},${b},0.18);color:${hex};border-color:rgba(${r},${g},${b},0.4)`;
}

function teamPill(teamId, teams) {
  const t = teams[teamId];
  if (!t) return '';
  return `<span class="team-pill" style="${getTeamStyle(teamId, teams)}">${t.short}</span>`;
}

function posBadge(pos) {
  const cls = pos === 1 ? 'p1' : pos === 2 ? 'p2' : pos === 3 ? 'p3' : '';
  return `<div class="pos-badge ${cls}">${pos}</div>`;
}

function driverLink(driverId, drivers) {
  const d = drivers[driverId];
  if (!d) return driverId;
  return `<a class="driver-name-link" href="driver.html?id=${driverId}">${d.name}</a>`;
}

function driverCell(driverId, drivers) {
  const d = drivers[driverId];
  if (!d) return `<td>${driverId}</td>`;
  return `<td><div class="driver-name-cell"><span class="driver-flag">${d.flag || ''}</span>${driverLink(driverId, drivers)}</div></td>`;
}

function initTabs() {
  // ARIA tablist setup
  document.querySelectorAll('.tabs').forEach(tablist => {
    tablist.setAttribute('role', 'tablist');
  });

  document.querySelectorAll('.tab-btn').forEach(btn => {
    const tab = btn.dataset.tab;
    const group = btn.dataset.tabGroup || 'default';
    const panelId = `tabpanel-${tab}-${group}`;
    const btnId = `tab-${tab}-${group}`;

    btn.id = btnId;
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-selected', 'false');
    btn.setAttribute('aria-controls', panelId);

    const panel = document.querySelector(`.tab-panel[data-tab="${tab}"][data-tab-group="${group}"]`);
    if (panel) {
      panel.id = panelId;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', btnId);
      panel.setAttribute('tabindex', '0');
    }

    btn.addEventListener('click', () => {
      document.querySelectorAll(`.tab-btn[data-tab-group="${group}"]`).forEach(b => {
        b.classList.remove('active');
        b.setAttribute('aria-selected', 'false');
      });
      document.querySelectorAll(`.tab-panel[data-tab-group="${group}"]`).forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      document.querySelector(`.tab-panel[data-tab="${tab}"][data-tab-group="${group}"]`)?.classList.add('active');
    });

    btn.addEventListener('keydown', (e) => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return;
      e.preventDefault();
      const allTabs = [...document.querySelectorAll(`.tab-btn[data-tab-group="${group}"]`)];
      const idx = allTabs.indexOf(btn);
      let target;
      if (e.key === 'ArrowRight') target = allTabs[(idx + 1) % allTabs.length];
      else if (e.key === 'ArrowLeft') target = allTabs[(idx - 1 + allTabs.length) % allTabs.length];
      else if (e.key === 'Home') target = allTabs[0];
      else if (e.key === 'End') target = allTabs[allTabs.length - 1];
      if (target) { target.click(); target.focus(); }
    });
  });

  // Activate first tab in each group
  const groups = new Set();
  document.querySelectorAll('.tab-btn').forEach(b => groups.add(b.dataset.tabGroup || 'default'));
  groups.forEach(g => {
    const first = document.querySelector(`.tab-btn[data-tab-group="${g}"]`);
    if (first && !document.querySelector(`.tab-btn[data-tab-group="${g}"].active`)) first.click();
  });
}

function initMobileNav() {
  const btn = document.getElementById('nav-hamburger');
  const links = document.getElementById('nav-links');
  if (!btn || !links) return;

  btn.addEventListener('click', () => {
    const isOpen = links.classList.toggle('open');
    btn.setAttribute('aria-expanded', String(isOpen));
    btn.setAttribute('aria-label', isOpen ? 'Close navigation menu' : 'Open navigation menu');
  });

  // Close on link click
  links.querySelectorAll('a').forEach(a => {
    a.addEventListener('click', () => {
      links.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
      btn.setAttribute('aria-label', 'Open navigation menu');
    });
  });

  // Close on resize to desktop
  window.addEventListener('resize', () => {
    if (window.innerWidth > 700) {
      links.classList.remove('open');
      btn.setAttribute('aria-expanded', 'false');
    }
  });
}

document.addEventListener('DOMContentLoaded', initMobileNav);

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function countryFlag(code) {
  if (!code) return '';
  return code.toUpperCase().replace(/./g, c => String.fromCodePoint(c.charCodeAt(0) + 127397));
}

function initNav(activePage) {
  const nav = document.getElementById('nav');
  if (!nav) return;
  nav.querySelectorAll('a').forEach(a => {
    if (a.dataset.page === activePage) a.classList.add('active');
  });
}

function buildStandingsTable(standings, db, showGap = true) {
  if (!standings || standings.length === 0) return '<p style="color:var(--text-muted);padding:1rem 0">No standings data yet.</p>';
  const leader = standings[0]?.points || 0;
  return `
  <table class="standings-table">
    <thead>
      <tr>
        <th style="width:40px">Pos</th>
        <th>Driver</th>
        <th>Team</th>
        <th><abbr title="Wins">W</abbr></th><th><abbr title="Podiums">P</abbr></th>
        <th>Pts</th>
        ${showGap ? '<th>Gap</th>' : ''}
      </tr>
    </thead>
    <tbody>
      ${standings.map((s, i) => {
        const d = db.drivers[s.driver];
        const gap = s.points === leader ? '—' : '+' + (leader - s.points);
        return `<tr class="${i === 0 ? 'leader' : ''}">
          <td>${posBadge(s.pos)}</td>
          ${driverCell(s.driver, db.drivers)}
          <td>${teamPill(s.team, db.teams)}</td>
          <td>${s.wins ?? 0}</td>
          <td>${s.podiums ?? 0}</td>
          <td class="pts-cell">${s.points}</td>
          ${showGap ? `<td class="gap-cell">${gap}</td>` : ''}
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}

function buildConstructorTable(standings, db) {
  if (!standings || standings.length === 0) return '<p style="color:var(--text-muted);padding:1rem 0">No data yet.</p>';
  const leader = standings[0]?.points || 0;
  return `
  <table class="standings-table">
    <thead>
      <tr>
        <th style="width:40px">Pos</th>
        <th>Constructor</th>
        <th>Points</th>
        <th>Gap</th>
      </tr>
    </thead>
    <tbody>
      ${standings.map((s, i) => {
        const t = db.teams[s.team];
        const gap = s.points === leader ? '—' : '+' + (leader - s.points);
        return `<tr class="${i === 0 ? 'leader' : ''}">
          <td>${posBadge(s.pos)}</td>
          <td>${teamPill(s.team, db.teams)}&nbsp;&nbsp;<span style="color:var(--text-primary)">${t?.name || s.team}</span></td>
          <td class="pts-cell">${s.points}</td>
          <td class="gap-cell">${gap}</td>
        </tr>`;
      }).join('')}
    </tbody>
  </table>`;
}


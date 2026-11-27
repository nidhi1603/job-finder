/**
 * Job tracker for job-finder: a Google Sheet the hourly job finder writes new jobs into.
 *
 * Setup (once): in a blank Google Sheet open Extensions → Apps Script, replace everything with this file,
 * put your secret in SECRET below, save, then Deploy → New deployment → Web app
 * (Execute as: Me, Who has access: Anyone). Copy the web app URL into the SHEET_URL GitHub secret.
 * "Anyone" only means the job finder can reach it without a Google login; every request must carry SECRET.
 *
 * You only edit Status (dropdown) and Notes. Picking Applied, Interviewing, Offer or Rejected fills in
 * "Applied on". The Companies tab lists every company you applied to. Rows you add by hand count too.
 */
const SECRET = 'PASTE_SECRET_HERE';

const JOBS = 'Jobs';
const COMPANIES = 'Companies';
const HEADERS = ['Status', 'Fit', 'Group', 'Company', 'Job (click to open)', 'Posted', 'Location', 'Flags',
                 'Skills you have', 'Skills missing', 'Crowding', 'Found', 'Applied on', 'Notes', 'key'];
const C = {status: 1, fit: 2, group: 3, company: 4, title: 5, posted: 6, location: 7, flags: 8, matched: 9,
           missing: 10, crowd: 11, found: 12, applied: 13, notes: 14, key: 15};
const N = HEADERS.length;
const STATUSES = ['New', 'Applied', 'Interviewing', 'Offer', 'Rejected', 'Skipped'];
const APPLIED = ['Applied', 'Interviewing', 'Offer', 'Rejected'];

function doGet() {
  return ContentService.createTextOutput('Job tracker is running.');
}

function doPost(e) {
  let req;
  try {
    req = JSON.parse(e.postData.contents);
  } catch (err) {
    return out_({ok: false, error: 'bad request'});
  }
  if (!SECRET || SECRET === 'PASTE_SECRET_HERE' || req.secret !== SECRET) {
    return out_({ok: false, error: 'wrong secret'});
  }
  const lock = LockService.getScriptLock();
  lock.waitLock(60000);
  try {
    const sh = setup_();
    if (req.action === 'add') return out_(add_(sh, req.jobs || []));
    if (req.action === 'summary') return out_(summary_(sh, req.since));
    return out_({ok: false, error: 'unknown action'});
  } catch (err) {
    return out_({ok: false, error: String(err)});
  } finally {
    lock.releaseLock();
  }
}

/** Fills in "Applied on" when you set Status to Applied / Interviewing / Offer / Rejected. */
function onEdit(e) {
  const r = e.range;
  const sh = r.getSheet();
  if (sh.getName() !== JOBS || r.getRow() < 2 || r.getColumn() > C.status || r.getLastColumn() < C.status) return;
  for (let row = r.getRow(); row <= r.getLastRow(); row++) {
    const status = sh.getRange(row, C.status).getValue();
    const cell = sh.getRange(row, C.applied);
    if (APPLIED.indexOf(status) >= 0 && !cell.getValue()) cell.setValue(new Date());
  }
}

function add_(sh, jobs) {
  const rows = data_(sh);
  const keys = new Set(rows.map(r => String(r[C.key - 1])));
  const appliedAt = {};
  rows.forEach(r => {
    const d = r[C.applied - 1];
    if (d instanceof Date) {
      const c = norm_(r[C.company - 1]);
      if (!appliedAt[c] || d > appliedAt[c]) appliedAt[c] = d;
    }
  });
  const now = new Date();
  const annotations = {};
  const add = [];
  jobs.forEach((j, i) => {
    if (!j.key || keys.has(j.key)) return;
    keys.add(j.key);
    let flags = j.flags || '';
    const prev = appliedAt[norm_(j.company)];
    if (prev) {
      const note = 'You applied here ' + Utilities.formatDate(prev, Session.getScriptTimeZone(), 'MMM d');
      annotations[j.key] = note;
      flags = note + (flags ? ' · ' + flags : '');
    }
    const found = new Date(now.getTime() - i * 1000);   // one second apart keeps this batch in the order sent
    add.push(['New', j.fit == null ? '' : j.fit / 100, j.group || '', j.company || '', link_(j.url, j.title),
              day_(j.posted), j.location || '', flags, j.matched || '', j.missing || '', j.crowd || '',
              found, '', '', j.key]);
  });
  if (add.length) {
    const start = sh.getLastRow() + 1;
    const need = start + add.length - 1 - sh.getMaxRows();
    if (need > 0) sh.insertRowsAfter(sh.getMaxRows(), need);
    sh.getRange(start, 1, add.length, N).setValues(add);
    sh.getRange(start, C.status, add.length, 1).setDataValidation(statusRule_());
    sh.getRange(2, 1, sh.getLastRow() - 1, N).sort({column: C.found, ascending: false});   // newest first
  }
  return {ok: true, added: add.length, annotations: annotations, url: SpreadsheetApp.getActive().getUrl()};
}

function summary_(sh, since) {
  const cut = since ? new Date(since) : new Date(Date.now() - 24 * 3600 * 1000);
  const weekAgo = new Date(Date.now() - 7 * 24 * 3600 * 1000);
  const last = sh.getLastRow();
  const values = data_(sh);
  const formulas = last > 1 ? sh.getRange(2, C.title, last - 1, 1).getFormulas() : [];
  const tz = Session.getScriptTimeZone();
  const rows = [];
  let appliedTotal = 0, appliedWeek = 0;
  values.forEach((r, i) => {
    const applied = r[C.applied - 1];
    if (applied instanceof Date) {
      appliedTotal++;
      if (applied >= weekAgo) appliedWeek++;
    }
    const found = r[C.found - 1];
    if (!(found instanceof Date) || found < cut || !r[C.key - 1]) return;
    const m = /HYPERLINK\("([^"]*)"/.exec(formulas[i] ? formulas[i][0] : '');
    const posted = r[C.posted - 1];
    rows.push({
      status: r[C.status - 1] || 'New', fit: r[C.fit - 1] === '' ? null : Math.round(r[C.fit - 1] * 100),
      group: r[C.group - 1], company: r[C.company - 1], title: String(r[C.title - 1]), url: m ? m[1] : '',
      location: r[C.location - 1], flags: r[C.flags - 1],
      posted: posted instanceof Date ? Utilities.formatDate(posted, tz, 'MMM d') : ''
    });
  });
  return {ok: true, rows: rows, applied_total: appliedTotal, applied_week: appliedWeek,
          url: SpreadsheetApp.getActive().getUrl()};
}

/** Creates the Jobs and Companies tabs the first time the job finder calls in. */
function setup_() {
  const ss = SpreadsheetApp.getActive();
  let sh = ss.getSheetByName(JOBS);
  if (sh) return sh;
  sh = ss.insertSheet(JOBS, 0);
  sh.getRange(1, 1, 1, N).setValues([HEADERS]).setFontWeight('bold').setBackground('#f1f3f4');
  sh.setFrozenRows(1);
  const widths = [105, 50, 65, 150, 330, 70, 190, 280, 230, 200, 80, 130, 100, 220, 60];
  widths.forEach((w, i) => sh.setColumnWidth(i + 1, w));
  sh.getRange('B2:B').setNumberFormat('0%');
  sh.getRange('F2:F').setNumberFormat('mmm d');
  sh.getRange('L2:L').setNumberFormat('mmm d, h:mm am/pm');
  sh.getRange('M2:M').setNumberFormat('mmm d, yyyy');
  sh.getRange('H2:J').setWrap(false);
  sh.hideColumns(C.key);
  const all = sh.getRange('A2:N');
  const color = (formula, bg, font) => {
    const b = SpreadsheetApp.newConditionalFormatRule().whenFormulaSatisfied(formula).setRanges([all]);
    if (bg) b.setBackground(bg);
    if (font) b.setFontColor(font);
    return b.build();
  };
  sh.setConditionalFormatRules([
    color('=$A2="Offer"', '#fde68a'),
    color('=$A2="Interviewing"', '#dbeafe'),
    color('=$A2="Applied"', '#dcfce7'),
    color('=$A2="Rejected"', '#f3f4f6', '#9ca3af'),
    color('=$A2="Skipped"', null, '#9ca3af'),
    color('=$C2="Funded"', '#fff7e0'),
  ]);

  let co = ss.getSheetByName(COMPANIES) || ss.insertSheet(COMPANIES, 1);
  co.getRange('A1:B4').setValues([
    ['Applications', ''],
    ['Total applied', '=COUNT(Jobs!M2:M)'],
    ['Applied in the last 7 days', '=COUNTIF(Jobs!M2:M,">="&(TODAY()-6))'],
    ['Interviews and offers', '=COUNTIF(Jobs!A2:A,"Interviewing")+COUNTIF(Jobs!A2:A,"Offer")'],
  ]);
  co.getRange('A1').setFontWeight('bold').setFontSize(12);
  co.getRange('A6').setFormula(
    "=IFERROR(QUERY(Jobs!A2:N, \"select D, count(D), max(M) where M is not null group by D order by max(M) desc " +
    "label D 'Company', count(D) 'Roles applied', max(M) 'Last applied'\", 0), \"Companies appear here once you mark a job Applied.\")");
  co.getRange('A6:C6').setFontWeight('bold');
  co.getRange('C7:C').setNumberFormat('mmm d, yyyy');
  co.setColumnWidth(1, 220);
  co.setColumnWidth(2, 110);
  co.setColumnWidth(3, 120);

  const blank = ss.getSheetByName('Sheet1');
  if (blank && blank.getLastRow() === 0) ss.deleteSheet(blank);
  return sh;
}

function data_(sh) {
  const last = sh.getLastRow();
  return last > 1 ? sh.getRange(2, 1, last - 1, N).getValues() : [];
}

function statusRule_() {
  return SpreadsheetApp.newDataValidation().requireValueInList(STATUSES, true).setAllowInvalid(false).build();
}

function link_(url, title) {
  const t = String(title || 'Open').replace(/"/g, '""');
  if (!url) return t;
  return '=HYPERLINK("' + String(url).replace(/"/g, '%22') + '","' + t + '")';
}

function day_(s) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || '');
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : '';
}

function norm_(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

function out_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

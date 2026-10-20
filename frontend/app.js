const form = document.querySelector('#analyze-form');
const results = document.querySelector('#results');
const empty = document.querySelector('#empty');
const button = document.querySelector('#submit');
const watchBox = document.querySelector('#watch');
const watchStatus = document.querySelector('#watch-status');
const WATCH_INTERVAL_MS = window.WATCH_INTERVAL_MS || 8000;
let busy = false;
let watchTimer = null;

// Returns true when the analysis completed and the dashboard was updated.
async function runAnalysis(trigger = 'manual') {
  if (busy) return false;
  busy = true;
  const quiet = trigger === 'watch'; // keep the current results on screen while re-evaluating
  button.disabled = true;
  button.innerHTML = 'Analyzing…';
  if (!quiet) {
    results.classList.remove('hidden');
    results.innerHTML = '<p class="form-note">The five analysis stages are running locally…</p>';
  }
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: document.querySelector('#repo-path').value.trim(), trigger }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Analysis failed');
    render(data, { scroll: !quiet });
    empty.classList.add('hidden');
    return true;
  } catch (error) {
    if (quiet) setWatchStatus(`Re-evaluation failed: ${error.message}`);
    else results.innerHTML = `<p class="error">${escapeHtml(error.message)}. Start the API with <code>uvicorn backend.app:app --reload</code> and try again.</p>`;
    return false;
  } finally {
    busy = false;
    button.disabled = false;
    button.innerHTML = 'Analyze repository <span>↗</span>';
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  runAnalysis('manual');
});

// ---- watch mode: the outer feedback loop ----
function setWatchStatus(text) {
  watchStatus.textContent = text;
}

async function checkForNewCommits() {
  if (busy) return;
  const repo = document.querySelector('#repo-path').value.trim();
  if (!repo) return;
  try {
    const response = await fetch('/api/status?repo_path=' + encodeURIComponent(repo));
    const status = await response.json();
    if (!response.ok) throw new Error(status.detail || 'Status check failed');
    if (!status.has_previous_run) {
      setWatchStatus('Analyze the repository once to start watching.');
    } else if (status.needs_reanalysis) {
      const count = status.new_commits ? Number(status.new_commits.count) : 0;
      setWatchStatus(`New commits detected${count ? ` (${count})` : ''}, re-evaluating…`);
      if (await runAnalysis('watch')) setWatchStatus(`Re-evaluated at ${new Date().toLocaleTimeString()}. Watching…`);
    } else {
      setWatchStatus(`Up to date · checked ${new Date().toLocaleTimeString()}`);
    }
  } catch (error) {
    setWatchStatus(`Watch check failed: ${error.message}`);
  }
}

watchBox.addEventListener('change', () => {
  clearInterval(watchTimer);
  watchTimer = null;
  if (watchBox.checked) {
    setWatchStatus('Watching for new commits…');
    checkForNewCommits();
    watchTimer = setInterval(checkForNewCommits, WATCH_INTERVAL_MS);
  } else {
    setWatchStatus('');
  }
});

function render(data, { scroll = true } = {}) {
  const summary = data.summary;
  const agents = data.agents.map(agent => `<span class="agent-pill" title="${escapeHtml(agent.detail)}">✓ ${escapeHtml(agent.name)}</span>`).join('');
  const languages = Object.entries(summary.languages || {}).map(([name, count]) => `${escapeHtml(name)} ${count}`).join(' · ') || 'No supported source files found';
  const roadmap = data.roadmap.map(sprint => `<article class="sprint"><h3>${escapeHtml(sprint.name)} <span class="agent-count">${sprint.items.length} items · ${sprint.estimated_hours}h${sprint.capacity_hours ? ` / ${sprint.capacity_hours}h` : ''}</span></h3><p class="sprint-focus">${escapeHtml(sprint.focus)}${sprint.over_capacity ? ' · Over capacity' : ''}</p>${sprint.items.slice(0, 12).map(item => `<div class="finding"><b>${escapeHtml(item.file)}:${item.line} · ${escapeHtml(item.category)}</b><small> · ${item.priority} RISK · ${escapeHtml(item.confidence)} confidence${item.advice_source === 'llm' ? ' · AI advice' : ''}</small><p>${escapeHtml(item.message)}</p><p>${escapeHtml(item.explanation)}</p><p><strong>Next:</strong> ${escapeHtml(item.recommendation)}</p><div class="score-factors">${item.score_factors.map(factor => `<span>${escapeHtml(factor.name)} +${factor.points}</span>`).join('')} · ~${item.estimated_hours}h</div></div>`).join('') || '<p class="form-note">No findings in this group.</p>'}${sprint.items.length > 12 ? `<p class="form-note">Showing 12 of ${sprint.items.length} items in this group.</p>` : ''}</article>`).join('');
  const health = data.repository_health || {};
  const churn = (health.most_changed || []).map(item => `<span>${escapeHtml(item.file)} (${item.commits})</span>`).join(' · ') || 'No recent Git churn data';
  results.innerHTML = `<div class="result-header"><div><p class="eyebrow">ANALYSIS COMPLETE</p><h2>${escapeHtml(data.repository)}</h2></div></div><div class="metrics"><div class="metric"><b>${summary.files_scanned}</b><span>Files scanned</span></div><div class="metric"><b>${summary.findings}</b><span>Findings</span></div><div class="metric"><b>${summary.high_priority}</b><span>High priority</span></div><div class="metric"><b>${summary.average_priority}</b><span>Average risk</span></div><div class="metric"><b>${summary.commits_analyzed}</b><span>Commits reviewed</span></div></div><p class="meta-line"><strong>Languages:</strong> ${languages} &nbsp; <strong>Large files:</strong> ${health.large_files || 0}</p><p class="meta-line"><strong>Most changed:</strong> ${churn}</p><div class="agent-status">${agents}</div>${renderHistory(data.history)}${renderOrchestration(data.orchestration)}<div class="roadmap">${roadmap}</div><p class="form-note">${data.limitations.map(escapeHtml).join(' ')}</p>`;
  if (scroll) results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

// ---- analysis history panel ----
function signed(value) {
  const number = Number(value) || 0;
  return (number > 0 ? '+' : '') + number;
}

function historyList(title, items, describe) {
  if (!items || !items.length) return '';
  return `<details><summary>${escapeHtml(title)} (${items.length})</summary><ul>${items.map(item => `<li>${describe(item)}</li>`).join('')}</ul></details>`;
}

function renderHistory(history) {
  if (!history) return '';
  if (!history.available) return `<p class="form-note">${escapeHtml(history.reason || 'Analysis history is unavailable.')}</p>`;
  const runs = (history.recent_runs || []).map(run => `#${Number(run.id)} · ${Number(run.high_priority)} high · ${Number(run.average_priority)} avg`).join('  ←  ');
  if (history.first_run) {
    return `<div class="history"><p class="eyebrow">ANALYSIS HISTORY</p><p class="meta-line">First analysis of this repository (run #${Number(history.run_id)}). Analyze again after new commits to see what changed.</p></div>`;
  }
  const when = history.previous_run ? new Date(history.previous_run.analyzed_at).toLocaleString() : '';
  const counts = history.comparison.counts;
  const deltas = history.deltas;
  const commits = history.new_commits
    ? `${Number(history.new_commits.count)} new commit${history.new_commits.count === 1 ? '' : 's'}`
    : (history.head_changed ? 'commit history changed' : 'no new commits');
  const direction = value => (value > 0 ? 'up' : value < 0 ? 'down' : '');
  const chips = [
    `<span>${commits}</span>`,
    `<span class="${counts.new ? 'up' : ''}">${Number(counts.new)} new findings</span>`,
    `<span class="${counts.resolved ? 'down' : ''}">${Number(counts.resolved)} resolved</span>`,
    `<span>${Number(counts.changed)} priority changes</span>`,
    `<span class="${direction(deltas.high_priority)}">high priority ${signed(deltas.high_priority)}</span>`,
    `<span class="${direction(deltas.average_priority)}">average risk ${signed(deltas.average_priority)}</span>`,
  ].join('');
  const where = item => `${escapeHtml(item.file)}:${Number(item.line)} · ${escapeHtml(item.category)}`;
  const recentCommits = historyList('New commits', history.new_commits && history.new_commits.recent,
    commit => `<b>${escapeHtml(commit.hash)}</b> ${escapeHtml(commit.subject)}`);
  const lists = recentCommits
    + historyList('New findings', history.comparison.new, item => `${where(item)} · ${Number(item.priority)} risk`)
    + historyList('Resolved findings', history.comparison.resolved, item => `${where(item)} · was ${Number(item.priority)} risk`)
    + historyList('Priority changes', history.comparison.changed, item =>
        `${where(item)} · ${Number(item.previous_priority)} → ${Number(item.priority)}${item.reason ? ` (${escapeHtml(item.reason)})` : ''}`);
  return `<div class="history"><p class="eyebrow">SINCE LAST ANALYSIS · ${escapeHtml(when)}</p><div class="history-chips">${chips}</div>${lists}<p class="meta-line">Recent runs: ${escapeHtml(runs)}</p></div>`;
}

// ---- orchestration panel ----
function renderOrchestration(orchestration) {
  if (!orchestration) return '';
  const engine = orchestration.engine === 'langgraph' ? 'LangGraph' : 'Sequential fallback';
  const started = orchestration.trigger === 'watch' ? ' · started automatically by new commits' : '';
  const trace = (orchestration.trace || []).map(escapeHtml).join(' → ');
  const loops = (orchestration.reevaluations || []).map(event => {
    const commits = event.new_commits
      ? `${Number(event.new_commits)} new commit${event.new_commits === 1 ? '' : 's'} landed during analysis`
      : 'The repository changed during analysis';
    const total = Number(event.affected_total);
    const files = (event.affected_files || []).slice(0, 5).map(escapeHtml).join(', ');
    return `<p class="meta-line"><strong>Feedback loop:</strong> ${commits} (${escapeHtml(event.from_commit)} → ${escapeHtml(event.to_commit)}). ${total} file${total === 1 ? '' : 's'} affected${files ? ` (${files}${total > 5 ? ', …' : ''})` : ''}; sent back through Risk Assessment, ${Number(event.findings_in_affected_files)} finding${event.findings_in_affected_files === 1 ? '' : 's'} in those files re-scored.</p>`;
  }).join('');
  const unsettled = orchestration.settled === false
    ? '<p class="form-note">The repository was still changing when the re-evaluation limit was reached. Analyze again to catch up.</p>' : '';
  return `<div class="history orchestration"><p class="eyebrow">ORCHESTRATION · ${engine}${started}</p><p class="trace">${trace}</p>${loops}${unsettled}</div>`;
}

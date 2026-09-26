const form = document.querySelector('#analyze-form');
const results = document.querySelector('#results');
const empty = document.querySelector('#empty');
const button = document.querySelector('#submit');

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  button.innerHTML = 'Analyzing…';
  results.classList.remove('hidden');
  results.innerHTML = '<p class="form-note">The five analysis stages are running locally…</p>';
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo_path: document.querySelector('#repo-path').value.trim() }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Analysis failed');
    render(data);
    empty.classList.add('hidden');
  } catch (error) {
    results.innerHTML = `<p class="error">${escapeHtml(error.message)}. Start the API with <code>uvicorn backend.app:app --reload</code> and try again.</p>`;
  } finally {
    button.disabled = false;
    button.innerHTML = 'Analyze repository <span>↗</span>';
  }
});

function render(data) {
  const summary = data.summary;
  const agents = data.agents.map(agent => `<span class="agent-pill" title="${escapeHtml(agent.detail)}">✓ ${escapeHtml(agent.name)}</span>`).join('');
  const languages = Object.entries(summary.languages || {}).map(([name, count]) => `${escapeHtml(name)} ${count}`).join(' · ') || 'No supported source files found';
  const roadmap = data.roadmap.map(sprint => `<article class="sprint"><h3>${escapeHtml(sprint.name)} <span class="agent-count">${sprint.items.length} items · ${sprint.estimated_hours}h${sprint.capacity_hours ? ` / ${sprint.capacity_hours}h` : ''}</span></h3><p class="sprint-focus">${escapeHtml(sprint.focus)}${sprint.over_capacity ? ' · Over capacity' : ''}</p>${sprint.items.slice(0, 12).map(item => `<div class="finding"><b>${escapeHtml(item.file)}:${item.line} · ${escapeHtml(item.category)}</b><small> · ${item.priority} RISK · ${escapeHtml(item.confidence)} confidence</small><p>${escapeHtml(item.message)}</p><p>${escapeHtml(item.explanation)}</p><p><strong>Next:</strong> ${escapeHtml(item.recommendation)}</p><div class="score-factors">${item.score_factors.map(factor => `<span>${escapeHtml(factor.name)} +${factor.points}</span>`).join('')} · ~${item.estimated_hours}h</div></div>`).join('') || '<p class="form-note">No findings in this group.</p>'}${sprint.items.length > 12 ? `<p class="form-note">Showing 12 of ${sprint.items.length} items in this group.</p>` : ''}</article>`).join('');
  const health = data.repository_health || {};
  const churn = (health.most_changed || []).map(item => `<span>${escapeHtml(item.file)} (${item.commits})</span>`).join('') || 'No recent Git churn data';
  results.innerHTML = `<div class="result-header"><div><p class="eyebrow">ANALYSIS COMPLETE</p><h2>${escapeHtml(data.repository)}</h2></div></div><div class="metrics"><div class="metric"><b>${summary.files_scanned}</b><span>Files scanned</span></div><div class="metric"><b>${summary.findings}</b><span>Findings</span></div><div class="metric"><b>${summary.high_priority}</b><span>High priority</span></div><div class="metric"><b>${summary.average_priority}</b><span>Average risk</span></div><div class="metric"><b>${summary.commits_analyzed}</b><span>Commits reviewed</span></div></div><p class="meta-line"><strong>Languages:</strong> ${languages} &nbsp; <strong>Large files:</strong> ${health.large_files || 0}</p><p class="meta-line"><strong>Most changed:</strong> ${churn}</p><div class="agent-status">${agents}</div><div class="roadmap">${roadmap}</div><p class="form-note">${data.limitations.map(escapeHtml).join(' ')}</p>`;
  results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

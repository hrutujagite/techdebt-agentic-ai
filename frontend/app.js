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
  const agents = data.agents.map(agent => `<span class="agent-pill">✓ ${escapeHtml(agent.name)}</span>`).join('');
  const roadmap = data.roadmap.map(sprint => `<article class="sprint"><h3>${escapeHtml(sprint.name)} <span class="agent-count">${sprint.items.length} items</span></h3>${sprint.items.slice(0, 12).map(item => `<div class="finding"><b>${escapeHtml(item.file)}:${item.line} · ${escapeHtml(item.category)}</b><small> · ${item.priority} RISK</small><p>${escapeHtml(item.explanation)}</p><p><strong>Next:</strong> ${escapeHtml(item.recommendation)}</p></div>`).join('') || '<p class="form-note">No findings in this group.</p>'}</article>`).join('');
  results.innerHTML = `<div class="result-header"><div><p class="eyebrow">ANALYSIS COMPLETE</p><h2>${escapeHtml(data.repository)}</h2></div></div><div class="metrics"><div class="metric"><b>${summary.files_scanned}</b><span>Files scanned</span></div><div class="metric"><b>${summary.findings}</b><span>Findings</span></div><div class="metric"><b>${summary.high_priority}</b><span>High priority</span></div></div><div class="agent-status">${agents}</div><div class="roadmap">${roadmap}</div><p class="form-note">${data.limitations.map(escapeHtml).join(' ')}</p>`;
  results.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
}

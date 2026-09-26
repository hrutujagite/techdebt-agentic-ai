# Agentic AI System for Technical Debt Prioritization

An agentic AI system that turns scattered static analysis warnings into a single, explainable, prioritized roadmap for fixing technical debt. Instead of just flagging problems, this system decides what to fix first and explains why, reducing the time a team spends deciding what to fix, not the time spent fixing it.

## Problem

Static analysis tools like SonarQube and PMD generate hundreds of isolated warnings with no sense of priority, business impact, or historical risk. Developers end up spending more time arguing over what matters than actually fixing anything.

## Approach

Five specialized agents work together, each handling a different part of the reasoning process, with a feedback loop so the system stays current as the codebase changes.

- **Repository Analysis Agent** — mines Git commit history and code churn to find files that change constantly and tend to break things
- **Code Quality Agent** — runs SonarQube and PMD to collect static analysis warnings and code smells
- **Risk Assessment Agent** — combines both signals into one explainable priority score using XGBoost and SHAP
- **Refactoring Advisory Agent** — uses an LLM to explain, in plain language, why a file is risky and how to fix it
- **Planning Agent** — arranges the ranked list into a sprint-wise roadmap, and sends files back for re-evaluation when new commits land

## Tech Stack

- **Backend & Orchestration:** Python, FastAPI, LangGraph / CrewAI
- **Repository Mining:** GitPython, PyDriller
- **Static Analysis:** SonarQube, PMD
- **Machine Learning:** XGBoost / Random Forest, SHAP
- **LLM Layer:** used by the Refactoring Advisory Agent
- **Frontend:** React
- **Storage:** SQLite

## Team

Group 35, Department of Computer Engineering

| Name | Roll No |
|---|---|
| Christian V Bohia | 1023112 |
| Aaralyn Sarin | 1023118 |
| Hrutuja Gite | 1023134 |
| Aarya Hajgude | 1023136 |

**Guided by:** Mrs. Rakhi Kalantri

## Project Structure

```
├── repo_analysis/        # Inventory, language mix, Git change activity
├── code_quality/         # Language-aware heuristic source inspection
├── risk_assessment/      # Explainable severity, concentration, and churn score
├── refactor_advisory/    # Signal-specific remediation advice
├── planning/             # Risk-ranked workload and sprint capacity estimates
├── backend/               # FastAPI backend and agent orchestration
└── frontend/              # React dashboard
```

## Run the first version

The initial implementation is a lightweight local web dashboard backed by a
FastAPI service. It scans supported source files in a repository folder, checks
for common maintainability signals, uses recent Git churn when available, and
returns a ranked roadmap with an explanation and a suggested next step for each
finding. No API key or external service is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Open `http://localhost:8000` in a browser, enter the **absolute path** to a local
repository, and run the analysis. The dashboard is served by the API so its
requests stay on the same browser origin.
The health endpoint is available at `http://localhost:8000/api/health` and the
interactive API documentation at `http://localhost:8000/docs`.

The five `agent.py` modules are independently callable stages orchestrated by
`backend/analysis.py`. The scanner reports source-language mix and recent Git
activity, detects unfinished markers and selected risky patterns, computes an
explainable score with severity/concentration/churn factors, and estimates
effort against a configurable default sprint capacity. The dashboard displays
the evidence and recommendations per finding. Static checks and scoring remain
heuristic: the LLM, SonarQube, PMD, trained prediction model, persisted history,
and commit-triggered re-evaluation from the original proposal are not connected.
The API only reads the selected source tree and its Git history.

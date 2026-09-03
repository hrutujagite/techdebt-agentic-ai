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
├── repo_analysis/        # Repository Analysis Agent
├── code_quality/         # Code Quality Agent
├── risk_assessment/      # Risk Assessment Agent
├── refactor_advisory/    # Refactoring Advisory Agent
├── planning/             # Planning Agent
├── backend/               # FastAPI backend and agent orchestration
└── frontend/              # React dashboard
```

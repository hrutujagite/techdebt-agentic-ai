"""Group high-risk work and provide rough effort and sprint capacity estimates."""
EFFORT = {"dynamic code execution": 3, "shell execution": 3, "complex function": 3,
          "broad exception": 2, "FIXME": 2, "large file": 4, "TODO": 2,
          "HACK": 2, "disabled assertion": 1, "debug output": 1, "long line": 1}


def build_plan(findings: list[dict], sprint_capacity_hours: int = 16) -> list[dict]:
    groups = {"Sprint 1 · Stabilize": [], "Sprint 2 · Simplify": [], "Backlog · Maintain": []}
    for finding in sorted(findings, key=lambda f: (-f["priority"], f["file"], f["line"])):
        finding["estimated_hours"] = EFFORT.get(finding["category"], 2)
        key = "Sprint 1 · Stabilize" if finding["priority"] >= 65 else "Sprint 2 · Simplify" if finding["priority"] >= 40 else "Backlog · Maintain"
        groups[key].append(finding)
    result = []
    for name, items in groups.items():
        total = sum(i["estimated_hours"] for i in items)
        sprint = name.startswith("Sprint")
        result.append({"name": name, "items": items, "estimated_hours": total,
                       "capacity_hours": sprint_capacity_hours if sprint else None,
                       "over_capacity": sprint and total > sprint_capacity_hours,
                       "focus": "Address safety and explicit repair signals first." if name.startswith("Sprint 1") else
                               "Reduce structural complexity after urgent risks are contained." if name.startswith("Sprint 2") else
                               "Schedule lower risk cleanup alongside planned work."})
    return result

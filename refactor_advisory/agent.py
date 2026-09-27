"""Explain findings and suggest concrete remediation based on the signal."""
ADVICE = {
    "TODO": ("An unfinished marker can mean an implementation or decision is missing.", "Confirm the requirement, create or link a tracked work item, and implement it or remove the stale marker."),
    "FIXME": ("The code explicitly marks this behavior as needing repair.", "Reproduce the issue, add a regression test, fix the behavior, and remove the marker."),
    "HACK": ("A workaround can hide assumptions that later changes may break.", "Document the constraint it addresses and replace it with a tested solution when possible."),
    "debug output": ("Debug output can expose internal details or clutter production logs.", "Remove it or replace it with the project logger at an appropriate level."),
    "broad exception": ("Catching broad exceptions can hide unrelated failures and obscure recovery.", "Catch expected exception types, preserve useful context, and let unexpected errors surface."),
    "long line": ("The line may be harder to scan and review.", "Split the expression into named intermediate values or smaller statements while preserving behavior."),
    "dynamic code execution": ("Dynamic evaluation can execute input as code and is difficult to audit.", "Replace it with an explicit parser or dispatch table; strictly constrain inputs if dynamic evaluation is essential."),
    "shell execution": ("Invoking a shell expands the impact of untrusted command arguments.", "Pass an argument list with shell disabled and validate each argument."),
    "disabled assertion": ("This assertion always fails and may be leftover debugging or an unfinished branch.", "Implement the intended behavior or raise a specific, documented exception."),
    "complex function": ("Several branching paths make behavior and test coverage harder to reason about.", "Separate cohesive branches into small helpers and add focused tests for each path."),
    "large file": ("A large file can collect unrelated responsibilities and make safe edits harder.", "Extract cohesive sections behind small interfaces."),
        "Vulnerability": (
        "A vulnerability is a weakness that could be exploited to compromise confidentiality, integrity, or availability.",
        "Apply SonarQube's specific fix above, then add a test that would catch a regression."
    ),
    "Security Hotspot": (
        "A security hotspot needs a human judgment call about whether the code is actually exploitable in this context.",
        "Review the surrounding code to confirm whether it's a real risk, then fix it or mark it reviewed in SonarQube with a justification."
    ),
    "Bug": (
        "SonarQube flagged this as a likely functional defect, not just a style issue.",
        "Confirm the behavior with a test, then apply the fix described above."
    ),
    "Code Smell": (
        "A code smell doesn't break functionality but increases long-term review and maintenance cost.",
        "Apply the specific fix SonarQube suggests above, or refactor the pattern if it recurs elsewhere."
    ),
}


def advise(finding: dict, churn: int = 0) -> None:
    reason, action = ADVICE.get(finding["category"], ("This signal may increase maintenance effort.", "Review the surrounding code and add a focused test before changing behavior."))
    if churn:
        reason += f" The file appeared in {churn} recent commits, so its debt is in an actively changing area."
    finding["explanation"] = reason
    finding["recommendation"] = action

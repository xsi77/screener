# Agent Engineering Task

## Objective

Describe the exact engineering task.

## Repository

- Repo:
- Base branch:
- Target branch:

## Allowed Work

-

## Out of Scope

-

## Hard Prohibitions

- Do not implement auto-trading.
- Do not connect to broker execution APIs.
- Do not store secrets, API keys, tokens, passwords, or credentials.
- Do not push directly to main.
- Do not auto-merge.
- Do not delete user data.
- Do not modify protected strategy semantics unless explicitly authorized.

## Protected Areas

- BUY_CHECK logic
- engine
- signal_rules
- alert_rules
- strategy semantics
- screening conditions
- buy-point semantics
- broker / order execution / trade execution code
- live runtime secrets or credentials

## Required Verification

Agent must report:

- files changed
- commands run
- tests run
- test results
- git status
- diff summary
- risks
- incomplete items
- protected files touched: yes / no

## Local Review Gate

Before merge, human operator must run:

powershell -NoProfile -ExecutionPolicy Bypass -File "D:\AI工程指揮中心\scripts\review_pr.ps1" -RepoPath "D:\AI工程指揮中心\repos\<REPO_NAME>" -PrNumber <PR_NUMBER> -BaseBranch "main"

If tests exist, add:

-TestCommand ".\.venv\Scripts\python.exe -m pytest tests"

## Acceptance Criteria

- [ ] Task objective completed
- [ ] No forbidden behavior added
- [ ] No protected strategy semantics changed unless explicitly authorized
- [ ] Tests pass or test absence is justified
- [ ] Human review gate report generated

# Pull Request Review Template

## Summary

Describe what this PR changes.

## Task Source

- Issue:
- Agent / human:
- Branch:
- Base:

## Files Changed

-

## Verification

Commands run:

-

Results:

-

## Protected Area Check

- [ ] BUY_CHECK logic not modified
- [ ] engine not modified
- [ ] signal_rules not modified
- [ ] alert_rules not modified
- [ ] strategy semantics not modified
- [ ] broker / order execution code not added
- [ ] secrets / API keys / credentials not added
- [ ] no auto-trading behavior added
- [ ] no auto-merge requested

## Risk Assessment

Known risks:

-

Rollback plan:

-

## Required Agent Report

- files changed:
- tests run:
- git status:
- diff summary:
- risks:
- incomplete items:
- protected files touched: yes / no

## Human Review Gate

Before merge, run:

powershell -NoProfile -ExecutionPolicy Bypass -File "D:\AI工程指揮中心\scripts\review_pr.ps1" -RepoPath "D:\AI工程指揮中心\repos\<REPO_NAME>" -PrNumber <PR_NUMBER> -BaseBranch "main"

With tests when available:

-TestCommand ".\.venv\Scripts\python.exe -m pytest tests"

## Final Human Decision

- [ ] APPROVE
- [ ] REQUEST CHANGES
- [ ] REJECT
- [ ] KEEP AS DRAFT

# AGENTS.md

## Hard Rules

- Do not implement auto-trading.
- Do not connect to broker execution APIs.
- Do not store secrets, API keys, tokens, passwords, or credentials.
- Do not push directly to main.
- Do not auto-merge.
- Do not delete user data.
- Do not modify protected strategy semantics unless the issue explicitly authorizes it.

## Protected Areas

- BUY_CHECK logic
- engine
- signal_rules
- alert_rules
- strategy semantics
- screening conditions
- buy-point semantics

## Allowed Work

- Tests
- CI
- README
- deployment docs
- diagnostics
- logging
- run history
- provider fallback
- report formatting
- non-core refactor with tests

## Required Output

Every agent task must report:

- files changed
- tests run
- git status
- git diff summary
- risks
- incomplete items
- whether protected files were touched

## Trading Boundary

This repository is for screening, alerting, diagnostics, logging, and audit only.
It must never place orders automatically.
Human confirmation is required before any trade.

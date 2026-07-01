# Astra Production Launch Runbook

For the broader security and compliance remediation program that must sit behind any production-readiness or enterprise-security claim, see [Security Alignment Roadmap](/Users/ishaangubbala/Documents/Astra/docs/Security_Alignment_Roadmap.md).

This is the high-level operator path for proving Astra is ready to run as an Agent Stack Platform in production.

Exact environment inventories, founder identifiers, server targeting details, connector-seeding steps, and one-off operational commands are intentionally kept in local untracked notes.

## 1. Configure Production Requirements

Before launch, confirm that production auth, billing, alerting, credential storage, and required connectors are configured for the target stack. Production readiness should always be validated without printing secret values into logs, shell history, or tracked files.

## 2. Verify Platform Readiness

Verify health, readiness, metrics, stack catalog coverage, execution depth, connector validation, approvals, and objective-level launch readiness against the deployed environment. The final readiness signal should only be treated as complete after the saved report, evidence manifest, and bundle export all pass.

## 3. Run Final Production Verification

Run the final production gate against the deployed environment with live connector validation enabled. The gate must pass:

- Platform readiness.
- Runtime headroom.
- Stack template production-depth audit.
- Objective readiness.
- Billing and self-serve configuration.
- Alert delivery configuration.
- Live health, readiness, and metrics checks.
- Required connector live provider validation.
- Deploy evidence completeness.

Use the app settings panel or the production verification tooling in `backend/` and `deploy/` to run bootstrap, preflight, verification, and launch-proof flows. Keep any environment-specific command lines in local private notes rather than tracked Markdown.

## 4. Archive Evidence

Archive the saved verification report, checksum manifest, exported evidence bundle, and aggregate launch proof artifacts together. Verification evidence should remain tamper-evident and reproducible after archival.

## 5. Failure Handling

If the gate fails:

1. Read the missing-evidence or missing-config output.
2. Fix every missing env, config, or connector item.
3. Re-run the requirements and readiness checks.
4. Re-run final production verification with live connectors enabled.
5. Archive the next passing verification report.

Do not mark production launch complete from local tests alone. Completion requires a passing final verification report against the deployed production backend with real live connector credentials.

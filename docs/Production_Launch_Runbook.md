# Astra Production Launch Runbook

For the broader security and compliance remediation program that must sit behind any production-readiness or enterprise-security claim, see [Security Alignment Roadmap](/Users/ishaangubbala/Documents/Astra/docs/Security_Alignment_Roadmap.md).

This is the operator path for proving Astra is ready to run as an Agent Stack Platform in production.

## 1. Configure Production Requirements

Open the app settings page and use the `Production Gate` panel, or call:

```bash
deploy/production-env-missing.sh
python -m backend.production_env --env-file .env
python -m backend.production_env --env-file .env --print-missing-template
curl "$BACKEND_URL/admin/production-requirements?founder_id=<prod_founder>&stack_id=idea_to_revenue&base_url=$BACKEND_URL"
curl "$BACKEND_URL/admin/stack-catalog-proof"
curl "$BACKEND_URL/admin/production-bootstrap?founder_id=<prod_founder>&stack_id=idea_to_revenue&base_url=$BACKEND_URL"
curl "$BACKEND_URL/admin/production-preflight?base_url=$BACKEND_URL&expected_backend_ip=<server_ip>"
```

Required environment/config:

- `BACKEND_URL`: public HTTPS backend URL.
- `FRONTEND_URL`: public HTTPS frontend URL.
- `ASTRA_REQUIRE_AUTH=true`.
- `ASTRA_PLATFORM_ADMINS`: comma-separated platform admin user IDs.
- `ASTRA_JWT_JWKS_URL` or `ASTRA_JWT_SECRET`: production auth verification source.
- `ASTRA_CREDS_KEY`: stable connector credential encryption key.
- `ASTRA_ALERT_WEBHOOK_URL`: operations alert delivery webhook.
- `STRIPE_SECRET_KEY`: Stripe API key.
- `STRIPE_WEBHOOK_SECRET`: Stripe webhook signature secret.
- `STRIPE_PRICE_STARTER`, `STRIPE_PRICE_TEAM`, `STRIPE_PRICE_SCALE`: self-serve billing prices.

Required stack connectors depend on `stack_id`. The requirements report lists the exact connector keys and credential fields. Required connectors must pass live provider validation before launch.
Use `python -m backend.production_env --env-file .env` on the server to audit production env presence without exposing values. Use `python -m backend.production_env --env-file .env --print-missing-template` or `deploy/production-env-missing.sh` to print only missing `.env` keys as blank `KEY=` placeholders without exposing existing secret values.

## 2. Verify Platform Readiness

Check production health/readiness/metrics:

```bash
curl "$BACKEND_URL/health"
curl "$BACKEND_URL/ready"
curl "$BACKEND_URL/metrics"
```

Check the objective-level Agent Stack Platform contract:

```bash
curl "$BACKEND_URL/admin/objective"
curl "$BACKEND_URL/admin/objective/evidence?founder_id=<prod_founder>&stack_id=idea_to_revenue&base_url=$BACKEND_URL"
curl "$BACKEND_URL/admin/launch-readiness?founder_id=<prod_founder>&stack_id=idea_to_revenue&base_url=$BACKEND_URL&report_id=latest"
python -m backend.launch_readiness --founder-id <prod_founder> --stack-id idea_to_revenue --base-url "$BACKEND_URL" --report-id latest
```

The objective audit must show the stack catalog, stack execution depth, routing, Company Brain execution layer, connector ingestion, approvals, business controls, and production proof surface as ready.
The stack catalog proof must show every promised template compiles into a deployable execution package with lane packets, artifact acceptance checks, connector dependencies, approval gates, milestones, KPIs, quality gates, and completion audit criteria.
The evidence matrix must show `code_contract_ready=true`; `production_proven` only becomes true after a passing live connector verification report with a verified checksum manifest.
The launch-readiness audit is the final aggregate pass/fail gate. It must show `ok=true` after the saved report, manifest verification, and bundle export all pass.

## 3. Run Final Production Verification

CLI:

```bash
python -m backend.production_verify --founder-id <prod_founder> --stack-id idea_to_revenue --base-url "$BACKEND_URL" --live-connectors
python -m backend.production_launch --founder-id <prod_founder> --stack-id idea_to_revenue --base-url "$BACKEND_URL" --live-connectors --seed-env-connectors
```

Admin API:

```bash
curl -X POST "$BACKEND_URL/admin/production-verification?founder_id=<prod_founder>&stack_id=idea_to_revenue&base_url=$BACKEND_URL&live_connectors=true&save=true"
curl -X POST "$BACKEND_URL/admin/production-launch?founder_id=<prod_founder>&stack_id=idea_to_revenue&base_url=$BACKEND_URL&live_connectors=true&seed_env_connectors=true"
```

UI:

- Open `Settings`.
- Use `Production Gate`.
- Confirm the production API URL and stack ID.
- Keep `Validate live connector credentials` enabled.
- Click `Run final gate`.

The gate must pass:

- Platform readiness.
- Runtime headroom.
- Stack template production-depth audit.
- Objective readiness.
- Billing/self-serve config.
- Alert delivery config.
- Live `/health`, `/ready`, `/metrics`.
- Required connector live provider validation.
- Deploy evidence completeness.

Use `backend.production_launch` for the one-command final proof. It runs final verification, verifies the checksum manifest, exports the launch evidence bundle, and then runs aggregate launch-readiness. Live connector validation is enabled by default for this final proof command, and it exits nonzero unless every gate passes.

Use `--seed-env-connectors` when deployment-level tokens such as `GITHUB_TOKEN` and `VERCEL_TOKEN` should be reused as founder-scoped connector credentials for the proof run. The seeding report only returns field names and counts; it never prints secret values.

Before the final proof, run:

```bash
python -m backend.production_bootstrap --founder-id <prod_founder> --stack-id idea_to_revenue --base-url "$BACKEND_URL"
python -m backend.production_preflight --base-url "$BACKEND_URL" --expected-backend-ip <server_ip>
FOUNDER_ID=<prod_founder> STACK_ID=idea_to_revenue BACKEND_URL="$BACKEND_URL" EXPECTED_BACKEND_IP=<server_ip> deploy/server-preflight.sh
FOUNDER_ID=<prod_founder> STACK_ID=idea_to_revenue BACKEND_URL="$BACKEND_URL" EXPECTED_BACKEND_IP=<server_ip> deploy/production-proof.sh
```

Bootstrap returns missing env/config, connector seed status, operator steps, and the exact final proof command. Preflight verifies DNS points at the expected backend server and that `/health`, `/ready`, and `/metrics` are reachable on the public backend URL. `deploy/server-preflight.sh` is the production-server checklist for git revision, env presence, Docker services, local endpoints, DNS/API routing, and bootstrap status. `deploy/production-proof.sh` runs bootstrap, preflight, launch-readiness, and final production launch proof in fail-fast order.

## 4. Archive Evidence

A passing verification writes:

- `.astra/production_smoke/latest.json`
- `.astra/production_verification/latest.json`
- `.astra/production_verification/latest.md`
- `.astra/production_verification/latest.sha256.json`
- `.astra/production_launch/latest.json`
- `.astra/production_launch/latest.sha256.json`

Retrieve the latest reports:

```bash
curl "$BACKEND_URL/admin/production-verification/reports"
curl "$BACKEND_URL/admin/production-verification/reports/latest"
curl "$BACKEND_URL/admin/production-verification/reports/latest/markdown"
curl "$BACKEND_URL/admin/production-verification/reports/latest/manifest"
curl "$BACKEND_URL/admin/production-verification/reports/latest/manifest/verify"
curl -o astra-launch-evidence.zip "$BACKEND_URL/admin/production-verification/reports/latest/bundle"
curl "$BACKEND_URL/admin/production-launch/reports/latest"
curl "$BACKEND_URL/admin/production-launch/reports/latest/manifest"
curl "$BACKEND_URL/admin/production-launch/reports/latest/manifest/verify"
```

CLI equivalents after a saved verification:

```bash
python -m backend.production_verify --verify-manifest --report-id latest
python -m backend.production_verify --export-bundle --report-id latest
```

Archive `latest.md` plus `latest.sha256.json` as the launch proof, or archive the ZIP from `/bundle` which contains the report, Markdown proof, SHA-256 manifest, recomputed verification result, and source evidence files. Also archive `.astra/production_launch/latest.json` plus `.astra/production_launch/latest.sha256.json` so the aggregate launch proof is tamper-evident. Use both manifest verify endpoints to prove archived evidence still matches its SHA-256 manifests. The settings page also exposes `Open Markdown proof`, `Verify manifest`, and `Download proof bundle`.

## 5. Failure Handling

If the gate fails:

1. Read `deploy_evidence.missing`.
2. Fix every missing env/config/connector item.
3. Re-run `/admin/production-requirements`.
4. Re-run final production verification with `--live-connectors`.
5. Archive the next passing Markdown report.

Do not mark production launch complete from local tests alone. Completion requires a passing final verification report against the deployed production backend with real live connector credentials.

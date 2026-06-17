# Astra Security Alignment Roadmap

Last updated: June 17, 2026

## Purpose

This document is Astra's internal remediation roadmap for aligning the product and operating model with:

- [ISO/IEC 27001:2022](https://www.iso.org/standard/27001) as the primary information security management system anchor
- [ISO/IEC 27002:2022](https://www.iso.org/standard/75652.html) for control guidance
- [ISO/IEC 27005:2022](https://www.iso.org/standard/80585.html) for information security risk management
- [ISO/IEC 27018:2025](https://www.iso.org/standard/27018) for public-cloud PII protection guidance
- [CISA Secure by Design / Secure by Default](https://www.cisa.gov/securebydesign)
- [CISA Product Security Bad Practices](https://www.cisa.gov/resources-tools/resources/product-security-bad-practices)
- [CISA Cybersecurity Performance Goals 2.0](https://www.cisa.gov/cybersecurity-performance-goals-2-0-cpg-2-0)

This is an internal remediation document, not an external trust statement and not a certification claim.

## Current Conclusion

Astra is not yet ready to claim alignment with current CISA software manufacturer guidance or the ISO/IEC 27000-family baseline expected for a production SaaS handling customer data, connector credentials, and founder/company records.

The main blockers are not limited to app-code hardening. Astra still needs:

- Production-default security controls in the product
- Cloud/privacy control maturity appropriate for a SaaS platform
- A formal ISMS, risk register, and Statement of Applicability
- Evidence, logging, and operational proof that controls actually work

## Repo-Visible Findings

The following gaps are directly visible in the current repository and should be treated as the initial remediation set.

### Critical findings

1. Production authentication is not yet a mandatory default.
   - `backend/config.py` defaults `astra_require_auth` to `False`.
   - `backend/tenant_auth.py` still allows missing-user flows in non-required-auth mode and supports dev-style trust paths.

2. Frontend session protection is not production-safe by default.
   - `frontend/lib/auth.ts` allows a fallback `NEXTAUTH_SECRET`.
   - `frontend/lib/auth.ts` sets `useSecureCookies: false`, which is explicitly incompatible with a hardened HTTPS-only production posture.

3. Backend CORS is fully open.
   - `backend/main.py` sets `allow_origins=["*"]`, `allow_methods=["*"]`, and `allow_headers=["*"]`.

4. Sensitive operational data is still persisted in local/file-backed stores.
   - `backend/provisioning/credentials_store.py` stores encrypted connector credentials in a local vault path and can persist a generated key into `.env`.
   - The repo README explicitly documents a local-first storage model for several product surfaces.

5. Admin and observability surfaces are broad relative to a least-privilege production posture.
   - `backend/api/admin.py` exposes extensive operational and environment-facing endpoints under `/admin/*`.

### High-priority findings

1. No visible platform-wide rate limiting or abuse throttling is enforced for auth, run creation, admin, upload, OAuth, preview, or webhook endpoints.

2. No centralized immutable or write-restricted audit/security log design is documented.

3. The preview/local execution surface is called out as needing stronger auth enforcement.
   - `backend/api/preview_proxy.py` includes a TODO noting auth enforcement should be added when production auth is enabled.

4. The current PII lifecycle control is too narrow.
   - `backend/core/pii_vault.py` provides SSN-specific scrubbing and receipt purge logic, but not a platform-wide retention and deletion framework.

5. Security governance artifacts are missing from the repo.
   - No formal ISMS scope statement
   - No risk register
   - No Statement of Applicability
   - No security incident response plan
   - No documented supplier risk review process

## Alignment Targets

This roadmap distinguishes three thresholds. Astra should not collapse these into a single "compliant" claim.

### 1. Baseline alignment threshold

This is the minimum bar before Astra should claim internal alignment with the latest CISA guidance or an ISO/IEC 27001-ready security baseline.

Required outcomes:

- Production auth is mandatory
- HTTPS-only session handling is enforced
- CORS and admin surfaces are restricted
- Rate limiting and basic abuse controls exist
- Centralized security logging and incident ownership exist
- Sensitive data handling, retention, and deletion are defined

### 2. Enterprise customer review threshold

This is the minimum bar before Astra should present itself as enterprise-ready in security reviews or trust-center style discussions.

Required outcomes:

- The baseline threshold is complete
- MFA is enforced for privileged accounts
- Security policies and control owners are documented
- Supplier and subprocessor controls are documented
- Backups, restore tests, and vulnerability management are evidenced
- Security-facing public documentation exists

### 3. Formal ISO certification audit threshold

This is the minimum bar before engaging a formal ISO/IEC 27001 certification path.

Required outcomes:

- ISMS scope is approved
- Risk assessment and treatment plan are current
- Statement of Applicability is complete
- Internal audit and management review are operating
- Corrective action and evidence retention processes are active
- Control operation is demonstrated over time, not just implemented once

## Workstream 1: Product Hardening Before Any Alignment Claim

### Required changes

1. Enforce `ASTRA_REQUIRE_AUTH=true` in all non-development environments.
2. Remove or strictly isolate dev header trust and dev bearer bypass behavior from production code paths.
3. Require TLS end to end and enforce secure cookies:
   - no fallback production auth secret
   - `Secure`
   - `HttpOnly`
   - explicit `SameSite`
4. Replace wildcard CORS with explicit per-environment allowlists.
5. Add phishing-resistant MFA for platform admins and privileged operators, then standard MFA for all customer accounts.
6. Add rate limiting and abuse controls to:
   - auth endpoints
   - `/goal` and run-management flows
   - uploads
   - OAuth callback flows
   - `/admin/*`
   - preview/proxy routes
   - webhooks
7. Lock down admin surfaces with stronger authz, auditability, and break-glass procedures.
8. Add platform security headers:
   - HSTS
   - CSP
   - `frame-ancestors` or equivalent anti-clickjacking control
   - Referrer-Policy
   - Permissions-Policy
   - strict cache controls for authenticated responses
9. Treat preview/local execution as a high-risk surface and require:
   - authenticated access
   - tenant isolation
   - explicit kill-switches
   - auditable operator use
10. Reduce or remove local persistence for sensitive production data in favor of managed services with encryption, backup, and access logging.

### Definition of done

- Unauthenticated requests to user, company, connector, preview, and admin routes fail in production mode.
- Session cookies are HTTPS-only in staging and production.
- Wildcard CORS is eliminated from production.
- Admin operations are separately privileged and logged.
- Preview access is authenticated and tenant-scoped.

## Workstream 2: SaaS, Cloud, and Privacy Controls

### Required changes

1. Build and maintain an asset inventory covering:
   - prompts and run inputs
   - session logs and event history
   - generated artifacts
   - connector credentials and OAuth tokens
   - founder and company records
   - billing data
   - regulated or sensitive PII
2. Create a data-flow inventory showing how data moves between:
   - frontend
   - backend
   - local/managed storage
   - model providers
   - connector providers
   - deployment providers
3. Classify data and define retention and deletion rules for every store, extending beyond the current SSN-only handling.
4. Move secrets management to a managed secret store with rotation and least-privilege access.
5. Use managed KMS-backed encryption for sensitive production data where possible and document key ownership, rotation, and recovery.
6. Create supplier and connector security controls for:
   - model providers and routing vendors
   - Supabase
   - Vercel
   - Stripe
   - Google
   - GitHub
   - Redis
   - Composio-like integration layers
7. Define backup and disaster recovery targets:
   - RPO
   - RTO
   - restore ownership
   - restore test cadence
8. Establish vulnerability management:
   - dependency scanning
   - container scanning
   - secret scanning
   - SBOM generation
   - patch SLAs
   - tracked remediation
9. Establish secure SDLC controls:
   - threat modeling for major features
   - code review gates
   - security testing in CI
   - vulnerability disclosure intake
   - remediation transparency

### Definition of done

- Every production data store has a documented owner, classification, retention rule, and deletion path.
- Production secrets are not dependent on `.env` file persistence.
- Restore testing has been performed and recorded.
- Vulnerability and secret scanning run continuously in CI or release gates.

## Workstream 3: ISMS and Governance for ISO/IEC 27001 Readiness

### Required changes

1. Define the ISMS scope as:
   - Astra SaaS platform
   - supporting cloud infrastructure
   - desktop and web clients
   - connector platform
   - operational support functions
   - all personnel with production or customer-data access
2. Create and approve core policy documents:
   - access control
   - asset management
   - secure development
   - cryptography
   - logging and monitoring
   - vulnerability management
   - supplier security
   - incident response
   - backup and business continuity
   - change management
   - data retention and deletion
3. Run a formal ISO/IEC 27005-style risk assessment and create a risk register with:
   - risk statement
   - affected assets
   - likelihood and impact
   - owner
   - treatment
   - due date
   - residual risk acceptance
4. Create the Statement of Applicability mapped to selected ISO/IEC 27002 controls and document each inclusion or exclusion.
5. Assign control owners across engineering, infrastructure, support, and leadership.
6. Define review cadences, approvals, and evidence retention periods.
7. Establish security awareness and privileged-access procedures for employees and contractors.
8. Add internal audit, management review, corrective action tracking, and evidence preservation processes.

### Definition of done

- The ISMS scope is approved.
- The risk register is current and owned.
- The Statement of Applicability exists and is reviewable.
- Internal audit and management review have defined cadence and records.

## Workstream 4: Evidence and Operational Proof

### Required changes

1. Centralize application, access, admin, and security logs in a system with retention and restricted tamper capability.
2. Define incident severity levels, escalation paths, and response ownership.
3. Add monitoring and alerts for:
   - auth anomalies
   - token misuse
   - privilege changes
   - connector changes
   - data export/download activity
   - preview activity
   - admin actions
4. Produce and retain evidence artifacts:
   - architecture and data-flow diagrams
   - asset inventory
   - risk register
   - Statement of Applicability
   - access review records
   - backup restore reports
   - vulnerability scan reports
   - patch records
   - incident drill reports
   - change approvals
5. Establish minimum operating rhythm:
   - quarterly access reviews
   - quarterly vulnerability review
   - annual incident exercise
   - annual business continuity exercise

### Definition of done

- Security-relevant events are centrally logged and reviewable.
- Incident response ownership is documented and exercised.
- Required evidence artifacts exist and are current.

## Public/Product Expectations To Add

The product and customer-facing posture should change in the following ways:

- Authentication is mandatory in production.
- Dev auth behaviors are explicitly non-production only.
- Session handling is HTTPS-only.
- API clients should expect rate limiting and stricter CORS.
- Admin operations are privileged, narrower, and auditable.
- Security-facing documentation should exist for:
   - security overview
   - data retention
   - subprocessors/suppliers
   - vulnerability disclosure
   - incident handling summary

## Required Evidence Set

The following documents and records should exist before Astra claims a credible internal alignment baseline:

- ISMS scope statement
- Information security policy set
- Asset inventory
- Data-flow inventory
- Risk register
- Risk treatment plan
- Statement of Applicability
- Access review records
- Backup and restore evidence
- Vulnerability scan outputs and remediation records
- Supplier review records
- Incident response plan
- Incident or tabletop exercise records
- Change approval and release records

## Validation and Test Expectations

The following tests should be treated as mandatory acceptance checks for this roadmap:

1. Verify unauthenticated requests to user, company, admin, preview, and connector endpoints fail in production mode.
2. Verify MFA enforcement for admin users and privileged actions.
3. Verify secure cookie attributes and HTTPS-only session behavior in staging and production.
4. Verify CORS only allows approved origins and rejects wildcard behavior.
5. Verify rate limits trigger correctly on auth, goal creation, upload, OAuth, preview, webhook, and admin paths.
6. Verify secrets are not written to repo-tracked files or long-lived plaintext local stores.
7. Verify audit logs capture:
   - auth events
   - admin actions
   - permission changes
   - connector changes
   - data export/download actions
8. Verify backup restore from production-like data and document whether stated RPO/RTO targets were met.
9. Verify dependency, container, and secret scans run in CI and fail on defined severity thresholds.
10. Run at least one tabletop incident exercise and one restore exercise before making any alignment claim.

## Implementation Sequence

### Phase A: Blockers for baseline alignment claim

- Mandatory production auth
- HTTPS-only cookie/session hardening
- CORS restrictions
- Rate limiting
- Admin surface reduction and audit logging
- Preview auth and tenant isolation
- Centralized security logging
- Platform-wide retention/deletion policy

### Phase B: Blockers for enterprise customer reviews

- MFA for privileged users
- Supplier/security review process
- Backup and restore testing
- Vulnerability management pipeline
- Security overview and related customer-facing documents
- Incident response plan and on-call ownership

### Phase C: Blockers for formal ISO/IEC 27001 audit readiness

- Approved ISMS scope
- Risk register and treatment plan
- Statement of Applicability
- Internal audit process
- Management review process
- Corrective action tracking with evidence retention

## Assumptions

- This roadmap targets internal readiness for ISO/IEC 27001:2022 alignment, not an immediate certification claim.
- "Latest CISA" refers to the Secure by Design program, Product Security Bad Practices guidance, and Cybersecurity Performance Goals 2.0 current as of June 17, 2026.
- Because Astra is a cloud SaaS platform handling customer data and third-party connectors, cloud/privacy controls are in scope even if formal certification starts with ISO/IEC 27001.
- Any external statement about compliance, security posture, or certification should be reviewed against this roadmap and the actual evidence set, not engineering intent alone.

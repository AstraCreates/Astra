# Astra Desktop Signing And Release

Last updated: June 27, 2026

## Policy

Public Astra Desktop macOS releases must be signed, notarized, stapled, and verified before distribution. Ad-hoc builds are acceptable for local development only.

## What Stays In Tracked Docs

- the release policy
- the existence of the signed desktop workflow
- links to the official Tauri signing and notarization documentation
- high-level verification expectations

Detailed signing identities, CI secret names, certificate exports, download-host configuration, and step-by-step operator instructions are intentionally kept in local untracked notes.

## Official References

- Tauri macOS signing docs: [macOS Code Signing](https://v2.tauri.app/distribute/sign/macos/)
- Tauri environment variables: [Environment Variables](https://v2.tauri.app/reference/environment-variables/)
- Tauri GitHub pipeline guide: [GitHub](https://v2.tauri.app/distribute/pipelines/github/)

## Release Checklist

1. Confirm local or CI signing material is available through your private operational setup.
2. Run the signed desktop release workflow for the target version.
3. Verify the resulting `.app` is not ad-hoc signed.
4. Verify Gatekeeper acceptance and notarization ticket stapling.
5. Publish the DMG and checksum through the release channel used by the public download flow.

## Failure Signals

Investigate immediately if any of these occur:

- macOS reports the app as damaged or unsafe
- the build is ad-hoc signed
- notarization is missing or rejected
- the stapled ticket is absent

## Current Policy

Do not publish public DMGs from ad-hoc builds. Use the signed workflow and private operator runbook for every public macOS release.

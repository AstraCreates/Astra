# Changelog

All notable changes to Astra are documented here.

## [0.1.1] — 2026-06-22

### Fixed

- **Frontend hydration mismatch**: Move localStorage access to useEffect in RedesignSidebar to prevent SSR hydration errors
- **UI flashing on dashboard**: Stop resetting sessions list on every load, use silent refresh for background updates
- **Error messages**: Parse API error responses to extract human-readable detail/message/error fields instead of displaying raw JSON
- **API path mismatch**: Remove redundant /api/ prefix in LiveStatusPanel monitoring endpoint
- **Race condition in dispatch**: Fix duplicate sub-run guard in goal_engine.py to properly handle non-terminal session states

## [0.1.0] — Initial Release

Initial public release of Astra.

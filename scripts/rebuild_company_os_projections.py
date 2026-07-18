#!/usr/bin/env python3
"""Rebuild disposable Company OS Supabase-like and Graphiti-like projections."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.company_os_projection import rebuild_all_company_projections, rebuild_company_projections


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--company-id", help="Rebuild one Company OS company")
    selection.add_argument("--all", action="store_true", help="Rebuild every local Company OS company")
    parser.add_argument("--company-root", type=Path, help="Company OS root (default: workspace/company)")
    parser.add_argument("--projection-root", type=Path, help="Projection root (default: workspace/company-projections)")
    args = parser.parse_args()
    kwargs = {"company_root": args.company_root, "projection_root": args.projection_root}
    result = (rebuild_all_company_projections(**kwargs) if args.all
              else rebuild_company_projections(args.company_id, **kwargs))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the versioned component-reference SQLite release artifact."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.reference_db import ReferenceStore, compile_reference


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="directory containing reviewed YAML")
    parser.add_argument("--out", type=Path, required=True, help="compiled SQLite destination")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    manifest = compile_reference(args.source, args.out)
    if args.print_summary:
        with ReferenceStore(args.out) as store:
            categories = store.list_categories()
            snapshots = [store.snapshot(category["category_id"]) for category in categories]
        component_count = sum(len(snapshot["components"]) for snapshot in snapshots)
        null_lifecycle_count = sum(
            component["lifecycle"] is None
            for snapshot in snapshots
            for component in snapshot["components"]
        )
        non_null_lifecycle_count = component_count - null_lifecycle_count
        release_claim_count = len(categories)
        sourced_release_claim_count = sum(bool(category["source_ids"]) for category in categories)
        for snapshot in snapshots:
            claim_components = [
                component
                for component in snapshot["components"]
                if component["lifecycle"] is not None or component["safety_sensitive"]
            ]
            release_claim_count += len(claim_components) + len(snapshot["rules"])
            sourced_release_claim_count += sum(
                bool(component["source_ids"])
                and bool(component["evidence_grade"])
                and bool(component["reviewed_on"])
                for component in claim_components
            )
            sourced_release_claim_count += sum(
                bool(rule["source_ids"])
                and bool(rule["evidence_grade"])
                and bool(rule["reviewed_on"])
                for rule in snapshot["rules"]
            )
        print("component reference release summary")
        print(f"database version: {manifest.version}")
        print(f"schema version: {manifest.schema_version}")
        print(f"categories: {len(categories)}")
        for category in categories:
            print(f"- {category['category_id']}: {category['display_name']}")
        print(f"components: {component_count}")
        print(f"null lifecycles: {null_lifecycle_count}")
        print(f"sourced non-null lifecycles: {non_null_lifecycle_count}")
        print(
            "source coverage: "
            f"{sourced_release_claim_count}/{release_claim_count} release claims"
        )
        print(f"sha256: {manifest.content_sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

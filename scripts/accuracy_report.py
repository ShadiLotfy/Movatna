from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from booking_extractor import SCHEMA, parse_booking_pdf

EXPECTED_PATH = ROOT / "tests" / "expected_results.json"


def load_expected(path: Path) -> dict[str, dict[str, str]]:
    return json.loads(path.read_text(encoding="utf-8"))


def sample_pdfs() -> list[str]:
    return sorted(path.name for path in ROOT.glob("*.pdf"))


def build_report(expected: dict[str, dict[str, str]]) -> tuple[list[dict], dict[str, dict[str, int]]]:
    rows: list[dict] = []
    field_stats = {field: {"passed": 0, "total": 0} for field in SCHEMA}
    expected_names = set(expected)

    for filename, expected_row in expected.items():
        pdf_path = ROOT / filename
        if not pdf_path.exists():
            rows.append(
                {
                    "pdf": filename,
                    "passed": False,
                    "matchedFields": 0,
                    "totalFields": len(SCHEMA),
                    "mismatches": [{"field": "PDF", "expected": "file exists", "actual": "missing"}],
                }
            )
            continue
        actual = parse_booking_pdf(pdf_path)
        mismatches = []
        for field in SCHEMA:
            expected_value = expected_row.get(field, "")
            actual_value = actual.get(field, "")
            field_stats[field]["total"] += 1
            if actual_value == expected_value:
                field_stats[field]["passed"] += 1
            else:
                mismatches.append(
                    {
                        "field": field,
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
        rows.append(
            {
                "pdf": filename,
                "passed": len(mismatches) == 0,
                "matchedFields": len(SCHEMA) - len(mismatches),
                "totalFields": len(SCHEMA),
                "mismatches": mismatches,
            }
        )
    for filename in sample_pdfs():
        if filename not in expected_names:
            rows.append(
                {
                    "pdf": filename,
                    "passed": False,
                    "matchedFields": 0,
                    "totalFields": len(SCHEMA),
                    "mismatches": [
                        {
                            "field": "expected_results.json",
                            "expected": "PDF fixture entry",
                            "actual": "missing",
                        }
                    ],
                }
            )
    return rows, field_stats


def print_report(rows: list[dict], field_stats: dict[str, dict[str, int]]) -> None:
    total_fields = sum(item["totalFields"] for item in rows)
    matched_fields = sum(item["matchedFields"] for item in rows)
    print("PDF accuracy")
    for row in rows:
        status = "PASS" if row["passed"] else "FAIL"
        print(f"- {status} {row['pdf']}: {row['matchedFields']}/{row['totalFields']} fields")
        for mismatch in row["mismatches"]:
            print(
                f"  - {mismatch['field']}: expected {mismatch['expected']!r}, "
                f"got {mismatch['actual']!r}"
            )

    print("\nField accuracy")
    for field, stats in field_stats.items():
        print(f"- {field}: {stats['passed']}/{stats['total']}")

    print(f"\nOverall: {matched_fields}/{total_fields} fields matched")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare sample PDF extraction against expected_results.json.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()

    expected = load_expected(EXPECTED_PATH)
    rows, field_stats = build_report(expected)
    matched_fields = sum(item["matchedFields"] for item in rows)
    total_fields = sum(item["totalFields"] for item in rows)
    payload = {
        "pdfs": rows,
        "fields": field_stats,
        "overall": {
            "matchedFields": matched_fields,
            "totalFields": total_fields,
            "passed": matched_fields == total_fields,
        },
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print_report(rows, field_stats)
    return 0 if payload["overall"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

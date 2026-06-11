import json
import unittest
from pathlib import Path

from booking_extractor import SCHEMA, export_booking_data, format_equipment, parse_booking_pdf


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((Path(__file__).with_name("expected_results.json")).read_text(encoding="utf-8"))


class BookingExtractorTests(unittest.TestCase):
    def test_all_sample_pdfs_match_expected_results(self):
        for filename, expected in EXPECTED.items():
            with self.subTest(filename=filename):
                self.assertEqual(parse_booking_pdf(ROOT / filename), expected)

    def test_export_keeps_schema_order_for_frontend_and_csv(self):
        paths = [ROOT / filename for filename in EXPECTED]
        rows = export_booking_data(paths)

        self.assertEqual(len(rows), len(EXPECTED))
        for row in rows:
            self.assertEqual(list(row), SCHEMA)

    def test_equipment_normalization_handles_template_variants(self):
        examples = {
            "40'DRY  HC.-6": "6 x 40'HC",
            "3 40HCX": "3 x 40'HC",
            "15x45GP": "15 x 40'HC",
            "1 x 20'ST": "1 x 20'GP",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(format_equipment(raw), expected)


if __name__ == "__main__":
    unittest.main()

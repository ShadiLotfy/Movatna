import json
import unittest
from pathlib import Path

from booking_extractor import SCHEMA, calculated_cutoffs, clean_port, export_booking_data, format_equipment, parse_booking_pdf


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((Path(__file__).with_name("expected_results.json")).read_text(encoding="utf-8"))


class BookingExtractorTests(unittest.TestCase):
    def test_cutoff_examples_from_business_rules(self):
        examples = [
            ("Maersk", "22 Apr 2026 Wednesday", "16/04/2026", "15/04/2026", "16/04/2026"),
            ("COSCO", "22 Apr 2026 Wednesday", "19/04/2026", "16/04/2026", "19/04/2026"),
            ("MSC", "28 Apr 2026 Tuesday", "23/04/2026", "22/04/2026", "23/04/2026"),
            ("ONE", "30 Apr 2026 Thursday", "27/04/2026", "26/04/2026", "27/04/2026"),
            ("CMA CGM", "11 Jun 2026 Thursday", "08/06/2026", "07/06/2026", "08/06/2026"),
            ("MAERSK Line", "17 Jun 2026 Wednesday", "11/06/2026", "10/06/2026", "11/06/2026"),
        ]
        for carrier, ets, si_vgm, assigning, gate_in in examples:
            with self.subTest(carrier=carrier, ets=ets):
                self.assertEqual(
                    calculated_cutoffs(ets, carrier),
                    {"si_vgm": si_vgm, "assigning": assigning, "gate_in": gate_in},
                )

    def test_cutoff_rolls_friday_and_saturday_back_to_thursday(self):
        self.assertEqual(calculated_cutoffs("26 Jan 2026", "CMA CGM")["si_vgm"], "22/01/2026")
        self.assertEqual(calculated_cutoffs("19 May 2026", "Yang Ming")["si_vgm"], "14/05/2026")

    def test_cutoff_treats_sunday_as_working_day(self):
        cutoffs = calculated_cutoffs("22 Apr 2026", "COSCO")

        self.assertEqual(cutoffs["si_vgm"], "19/04/2026")
        self.assertEqual(cutoffs["gate_in"], cutoffs["si_vgm"])

    def test_pdf_stated_cutoffs_are_ignored(self):
        cosco = parse_booking_pdf(ROOT / "11.pdf")
        msc = parse_booking_pdf(ROOT / "MSC.pdf")

        self.assertEqual(cosco["Gate In Cut Off (Calculated)"], "26/01/2026")
        self.assertNotEqual(cosco["Gate In Cut Off (Calculated)"], "27/01/2026")
        self.assertEqual(msc["SI & VGM Cut Off (Calculated)"], "29/01/2026")
        self.assertNotEqual(msc["SI & VGM Cut Off (Calculated)"], "30/01/2026")

    def test_all_sample_pdfs_match_expected_results(self):
        for filename, expected in EXPECTED.items():
            with self.subTest(filename=filename):
                self.assertEqual(parse_booking_pdf(ROOT / filename), expected)

    def test_maersk_uses_first_transport_plan_vessel_and_voyage(self):
        row = parse_booking_pdf(ROOT / "MAERSK.pdf")

        self.assertEqual(row["Port of Loading"], "Port Said East")
        self.assertEqual(row["Vessel Name"], "LISA")
        self.assertEqual(row["Voyage No."], "605S")
        self.assertEqual(row["ETS POL / Sailing Date"], "31/01/2026")
        self.assertEqual(row["ETA POD / Arrival Date"], "27/02/2026")
        self.assertNotEqual(row["Vessel Name"], "MAERSK LEON")
        self.assertNotEqual(row["Voyage No."], "607S")

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
            "2 x 40HQ": "2 x 40'HQ",
            "3 x 40'HQ": "3 x 40'HQ",
            "4 x 40'HC": "4 x 40'HC",
        }
        for raw, expected in examples.items():
            with self.subTest(raw=raw):
                self.assertEqual(format_equipment(raw), expected)

    def test_port_normalization_repairs_rio_grande_spacing(self):
        self.assertEqual(clean_port("Rio Gr Ande"), "Rio Grande")
        self.assertEqual(clean_port("RIO GRANDE / BRAZIL"), "Rio Grande")


if __name__ == "__main__":
    unittest.main()

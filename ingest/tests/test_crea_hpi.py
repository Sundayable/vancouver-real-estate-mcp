"""Tests for the CREA archive link discovery and extraction.

Run from ingest/: python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common import DecodeError
from crea_hpi import extract_workbooks, find_zip_url, zip_month

FIXTURES = HERE / "fixtures"


class FindZipUrl(unittest.TestCase):
    def test_current_page(self):
        # September 2026 shape: no _EN suffix, underscores throughout, and two
        # MLS-HPI PDFs on the page that must not be mistaken for the archive.
        html = (FIXTURES / "crea_hpi_tool_2026-09.html").read_text(encoding="utf-8")
        self.assertEqual(
            find_zip_url(html),
            "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_Sept_2026.zip",
        )

    def test_previous_page_shape(self):
        html = '<a href="https://www.crea.ca/files/mls-hpi-data/MLS_HPI-July-2026_EN.zip">x</a>'
        self.assertEqual(
            find_zip_url(html),
            "https://www.crea.ca/files/mls-hpi-data/MLS_HPI-July-2026_EN.zip",
        )

    def test_relative_link(self):
        html = "<a class='btn' href='/files/mls-hpi-data/MLS_HPI_Oct_2026.zip'>Download</a>"
        self.assertEqual(
            find_zip_url(html),
            "https://www.crea.ca/files/mls-hpi-data/MLS_HPI_Oct_2026.zip",
        )

    def test_skips_french_and_prefers_newest(self):
        html = "".join(
            f'<a href="/files/mls-hpi-data/{name}">x</a>'
            for name in (
                "MLS_HPI_Aug_2026.zip",
                "MLS_HPI_Oct_2026_FR.zip",
                "MLS_HPI_Sept_2026.zip",
            )
        )
        self.assertTrue(find_zip_url(html).endswith("/MLS_HPI_Sept_2026.zip"))

    def test_no_link(self):
        html = '<a href="https://www.crea.ca/files/mls-hpi-data/english/Briefing.pdf">x</a>'
        with self.assertRaises(DecodeError):
            find_zip_url(html)

    def test_zip_month(self):
        self.assertEqual(zip_month("x/MLS_HPI_Sept_2026.zip"), (2026, 9))
        self.assertEqual(zip_month("x/MLS_HPI-July-2026_EN.zip"), (2026, 7))
        self.assertEqual(zip_month("x/MLS_HPI_latest.zip"), (0, 0))


class ExtractWorkbooks(unittest.TestCase):
    def test_replaces_last_months_copy(self):
        # data/raw is cached between CI runs; a workbook left from last month
        # must not survive into this month's parse.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            archive = tmp / "MLS_HPI_Sept_2026.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("Not Seasonally Adjusted (M).xlsx", b"september")
            out = tmp / "crea_hpi"
            out.mkdir()
            (out / "Not Seasonally Adjusted (M).xlsx").write_bytes(b"july")

            extracted = extract_workbooks(archive, out)

            self.assertEqual(list(extracted), ["Not Seasonally Adjusted (M).xlsx"])
            self.assertEqual(extracted["Not Seasonally Adjusted (M).xlsx"].read_bytes(), b"september")


if __name__ == "__main__":
    unittest.main()

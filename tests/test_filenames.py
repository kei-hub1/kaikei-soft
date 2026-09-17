import datetime as dt
import tempfile
import unittest
from pathlib import Path

from app.filenames import build_stem, sanitize_part, unique_stem


class SanitizeTest(unittest.TestCase):
    def test_replaces_invalid_characters(self):
        self.assertEqual(sanitize_part('a/b\\c:d*e?f"g<h>i|j'), "a／b＼c：d＊e？f”g＜h＞i｜j")

    def test_strips_and_collapses_spaces(self):
        self.assertEqual(sanitize_part("  資料　送付  "), "資料　送付")
        self.assertEqual(sanitize_part("a   b"), "a b")

    def test_empty_becomes_placeholder(self):
        self.assertEqual(sanitize_part(""), "無題")
        self.assertEqual(sanitize_part("..."), "無題")

    def test_truncates_long_text(self):
        self.assertEqual(len(sanitize_part("あ" * 100)), 40)


class StemTest(unittest.TestCase):
    def test_build_stem(self):
        self.assertEqual(
            build_stem(dt.date(2026, 9, 17), "株式会社サンプル", "資料送付のご案内"),
            "20260917_株式会社サンプル_資料送付のご案内",
        )

    def test_unique_stem_adds_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            self.assertEqual(unique_stem(directory, "x"), "x")
            (directory / "x.docx").touch()
            self.assertEqual(unique_stem(directory, "x"), "x_2")
            (directory / "x_2.pdf").touch()  # pdf だけ残っていても飛ばす
            self.assertEqual(unique_stem(directory, "x"), "x_3")


if __name__ == "__main__":
    unittest.main()

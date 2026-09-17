import datetime as dt
import unittest

from app.wareki import parse_date, to_wareki


class ToWarekiTest(unittest.TestCase):
    def test_reiwa(self):
        self.assertEqual(to_wareki(dt.date(2026, 9, 17)), "令和8年9月17日")

    def test_first_year_is_gannen(self):
        self.assertEqual(to_wareki(dt.date(2019, 5, 1)), "令和元年5月1日")
        self.assertEqual(to_wareki(dt.date(1989, 1, 8)), "平成元年1月8日")

    def test_heisei_last_day(self):
        self.assertEqual(to_wareki(dt.date(2019, 4, 30)), "平成31年4月30日")

    def test_showa(self):
        self.assertEqual(to_wareki(dt.date(1980, 12, 31)), "昭和55年12月31日")


class ParseDateTest(unittest.TestCase):
    def test_western_formats(self):
        expected = dt.date(2026, 9, 17)
        for s in ("2026/9/17", "2026/09/17", "2026-09-17", "2026.9.17", "20260917", "２０２６／９／１７", "2026年9月17日"):
            self.assertEqual(parse_date(s), expected, s)

    def test_wareki_formats(self):
        self.assertEqual(parse_date("令和8年9月17日"), dt.date(2026, 9, 17))
        self.assertEqual(parse_date("令和元年5月1日"), dt.date(2019, 5, 1))
        self.assertEqual(parse_date("R8/9/17"), dt.date(2026, 9, 17))
        self.assertEqual(parse_date("H31.4.30"), dt.date(2019, 4, 30))

    def test_invalid(self):
        for s in ("", "abc", "2026/13/1", "2026/2/30", "9/17"):
            self.assertIsNone(parse_date(s), s)


if __name__ == "__main__":
    unittest.main()

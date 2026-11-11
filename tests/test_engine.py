"""入力の中身（zaimu_input.py）のテスト。Windows がなくても動く。

実行:  python -m unittest discover tests
キーの送信と画面は、にせもの（FakeSender・FakeWin）に置き換えて、送る順番と止まり方を確かめる。
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import zaimu_input as z  # noqa: E402

HEADER = "日付,借方科目コード,貸方科目コード,金額,税区分,事業区分,取引先名,摘要,伝票メモ"


def write_csv(folder: Path, lines: list[str], name: str = "通帳.csv") -> Path:
    path = folder / name
    path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
    return path


def load(path: Path, tax: str = "課税"):
    """（設定, 月ごとの仕訳）。待ち時間は0にする。"""
    cfg = z.load_config(z.DEFAULT_CONFIG)
    cfg["timing"] = {"key_interval": 0, "paste_wait": 0, "row_wait": 0, "resume_wait": 0,
                     "switch_timeout": 0.3, "row_start_timeout": 0.3}
    for step in cfg["steps"] + cfg["month_switch"]:
        step.wait = 0
    header, rows, errors = z.load_rows(path, cfg, {"消費税": tax})
    assert not errors, errors
    groups = z.group_by_month(rows)
    for month_rows in groups.values():
        problems = z.apply_tax(month_rows, cfg) + z.validate(month_rows, header, cfg)[0]
        assert not problems, problems
    return cfg, groups


class FakeWin:
    def __init__(self, title="会計伝票"):
        self.fg = (1, title, 100)

    def foreground(self):
        return self.fg


class FakeSender:
    def __init__(self):
        self.sent = []

    def before_type(self):
        pass

    def type_char(self, ch):
        self.sent.append(ch)

    def press(self, key):
        self.sent.append("{%s}" % key)

    def paste(self, text):
        self.sent.append("[%s]" % text)

    def text(self):
        return "".join(self.sent)


def make_runner(cfg, win=None):
    win = win or FakeWin()
    messages = []
    ctl = z.Controller(cfg, cfg["target"]["zaimu"], win, notify=messages.append)
    ctl.paused = False   # テストでは最初から動かす
    sender = FakeSender()
    return z.Runner(cfg, ctl, sender), ctl, sender, messages


def press_resume_later(ctl, delay=0.2, before=None):
    """少しあとに PgUp（再開）を押したことにする。"""
    def run():
        time.sleep(delay)
        if before:
            before()
        ctl._on_resume()
    threading.Thread(target=run, daemon=True).start()


class KeyOrderTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def keys_for(self, line: str, tax: str = "課税") -> str:
        cfg, groups = load(write_csv(self.dir, [line]), tax)
        runner, _, sender, _ = make_runner(cfg)
        rows = next(iter(groups.values()))
        runner.run_rows(rows, 0, z.Progress(self.dir / "p.json", "2026-01"), notify=lambda m: None,
                        log_file=self.dir / "log.txt")
        return sender.text()

    def test_non_taxable_row(self):
        self.assertEqual(self.keys_for("2026/01/05,9411,1113,\"1,640\",0,,サンプル農協,肥料代,"),
                         "0{ENTER}9411{ENTER}1113{ENTER}5{ENTER}1640{ENTER}0{ENTER}[サンプル農協]{ENTER}0{ENTER}[肥料代]{ENTER}")

    def test_empty_tax_code_is_zero_only_for_non_taxable_accounts(self):
        self.assertTrue(self.keys_for("2026/01/05,1113,9311,500,,,入金,振込,").startswith("0{ENTER}1113"))
        cfg = z.load_config(z.DEFAULT_CONFIG)
        _, rows, _ = z.load_rows(write_csv(self.dir, ["2026/01/05,7513,1113,500,,,店,振込,"]), cfg, {"消費税": "課税"})
        self.assertIn("税区分が空です", z.apply_tax(rows, cfg)[0])

    def test_purchase_row_presses_enter_for_purchase_date(self):
        self.assertEqual(self.keys_for("2026/01/25,7513,1113,3300,5,,架空農機,草刈機の刃,"),
                         "5{ENTER}7513{ENTER}1113{ENTER}25{ENTER}3300{ENTER}0{ENTER}[架空農機]{ENTER}{ENTER}0{ENTER}[草刈機の刃]{ENTER}")

    def test_sales_row_types_business_code(self):
        self.assertTrue(self.keys_for("2026/01/25,1113,4111,12000,1,6,直売所,野菜売上,")
                        .startswith("1{ENTER}6{ENTER}1113{ENTER}4111{ENTER}"))

    def test_exempt_client_skips_tax_fields(self):
        self.assertEqual(self.keys_for("2026/01/25,7513,1113,3300,5,,架空農機,草刈機の刃,", tax="免税"),
                         "7513{ENTER}1113{ENTER}25{ENTER}3300{ENTER}0{ENTER}[架空農機]{ENTER}0{ENTER}[草刈機の刃]{ENTER}")

    def test_sub_code_from_screen_goes_to_bank_account_rows(self):
        cfg = z.load_config(z.DEFAULT_CONFIG)
        _, rows, _ = z.load_rows(write_csv(self.dir, ["2026/01/05,9411,1113,500,0,,店,振込,"]), cfg, {"消費税": "課税"})
        self.assertEqual(z.apply_sub_code(rows, "1113", "2"), [])
        self.assertEqual(rows[0].values["貸方補助コード"], "2")
        self.assertEqual(rows[0].values.get("借方補助コード", ""), "")

    def test_sub_code_on_other_account_is_typed_after_account(self):
        """雑費・租税公課など、普通預金以外の科目の補助コードは CSV から入れる。"""
        path = self.dir / "補助.csv"
        path.write_text("日付,借方科目コード,借方補助コード,貸方科目コード,金額,取引先名,摘要\n"
                        "2026/01/05,6229,3,1113,7000,固定資産税,税金\n", encoding="utf-8")
        cfg, groups = load(path, "免税")
        z.apply_sub_code(groups[(2026, 1)], "1113", "2")   # 画面で入れた普通預金の補助コード
        runner, _, sender, _ = make_runner(cfg)
        runner.run_rows(groups[(2026, 1)], 0, z.Progress(self.dir / "p.json", "2026-01"),
                        notify=lambda m: None, log_file=self.dir / "log.txt")
        self.assertTrue(sender.text().startswith("6229{ENTER}3{ENTER}1113{ENTER}2{ENTER}5{ENTER}7000"), sender.text())

    def test_same_account_with_and_without_sub_code_is_an_error(self):
        path = self.dir / "補助.csv"
        path.write_text("日付,借方科目コード,借方補助コード,貸方科目コード,金額,取引先名,摘要\n"
                        "2026/01/05,6229,3,1113,7000,固定資産税,税金\n"
                        "2026/01/06,6229,,1113,8000,自動車税,税金\n", encoding="utf-8")
        cfg = z.load_config(z.DEFAULT_CONFIG)
        header, rows, _ = z.load_rows(path, cfg, {"消費税": "免税"})
        z.apply_tax(rows, cfg)
        self.assertTrue(any("6229" in e and "混ざって" in e for e in z.validate(rows, header, cfg)[0]))

    def test_memo_with_line_break_does_not_shift_rows(self):
        path = write_csv(self.dir, ['2026/01/05,9411,1113,500,0,,店,振込,"1行目\n2行目"', "2026/01/06,9411,1113,700,0,,店,振込,"])
        _, rows, errors = z.load_rows(path, z.load_config(z.DEFAULT_CONFIG))
        self.assertEqual((errors, [r.values["金額"] for r in rows]), ([], ["500", "700"]))


class MonthSwitchTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_next_month_switches_automatically(self):
        cfg, _ = load(write_csv(self.dir, ["2026/01/05,9411,1113,500,0,,店,振込,"]))
        runner, _, sender, messages = make_runner(cfg)
        runner.switch_month((2026, 1), (2026, 2), "税区分")
        self.assertEqual(sender.text(), "{F4}{ENTER}11{ENTER}{DOWN}{ENTER}{ENTER}")
        self.assertEqual(messages, [])

    def test_skipped_month_pauses_instead_of_switching(self):
        """1月の次が3月のとき、「1行下」で切り替えると2月に入力してしまう。キーを送らずに止まる。"""
        cfg, _ = load(write_csv(self.dir, ["2026/01/05,9411,1113,500,0,,店,振込,"]))
        runner, ctl, sender, messages = make_runner(cfg)
        press_resume_later(ctl)
        runner.switch_month((2026, 1), (2026, 3), "税区分")
        self.assertEqual(sender.text(), "")
        self.assertIn("3月分に切り替え", messages[0])

    def test_year_change_pauses(self):
        cfg, _ = load(write_csv(self.dir, ["2026/01/05,9411,1113,500,0,,店,振込,"]))
        runner, ctl, sender, _ = make_runner(cfg)
        press_resume_later(ctl)
        runner.switch_month((2025, 12), (2026, 1), "税区分")
        self.assertEqual(sender.text(), "")

    def test_pauses_when_entry_screen_does_not_open(self):
        """切り替えのあと、会計伝票が最前面に出なければ、仕訳のキーを送る前に止まる。"""
        cfg, _ = load(write_csv(self.dir, ["2026/01/05,9411,1113,500,0,,店,振込,"]))
        win = FakeWin()
        runner, ctl, sender, messages = make_runner(cfg, win)
        ctl.checkpoint()   # 最初の画面（会計伝票）を入力先として覚える
        original_press = sender.press

        def press(key):
            original_press(key)
            if key == "F4":
                win.fg = (2, "処理の選択", 100)   # 切り替えの途中で止まったまま、という状況
        sender.press = press
        press_resume_later(ctl, delay=0.6)
        runner.switch_month((2026, 1), (2026, 2), "税区分")
        self.assertTrue(any("確かめられませんでした" in m for m in messages), messages)


class EntryWindowTest(unittest.TestCase):
    """仕訳の入力を始めてよい画面かどうかの確認。"""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cfg, groups = load(write_csv(self.dir, ["2026/01/05,9411,1113,100,0,,A,振込,",
                                                     "2026/01/06,9411,1113,200,0,,B,振込,"]))
        self.rows = groups[(2026, 1)]

    def run_rows(self, runner):
        runner.run_rows(self.rows, 0, z.Progress(self.dir / "p.json", "2026-01"), notify=lambda m: None,
                        log_file=self.dir / "log.txt")

    def test_tax_list_window_counts_as_entry_screen(self):
        """課税の関与先では、会計伝票に入るとすぐ「課税区分一覧」が前に出る。そこから始められる。"""
        runner, ctl, sender, messages = make_runner(self.cfg, FakeWin("課税区分一覧"))
        ctl.paused = True
        press_resume_later(ctl)
        self.run_rows(runner)
        self.assertIn("[B]", sender.text())
        self.assertFalse([m for m in messages if m.startswith("■")], messages)

    def test_other_window_at_start_is_refused(self):
        runner, ctl, sender, messages = make_runner(self.cfg, FakeWin("メモ帳"))
        ctl.paused = True
        press_resume_later(ctl)
        press_resume_later(ctl, delay=0.6, before=ctl.cancel)
        with self.assertRaises(z.Cancelled):
            self.run_rows(runner)
        self.assertEqual(sender.text(), "")
        self.assertIn("入力先ではありません", messages[0])

    def test_leftover_popup_stops_before_next_row(self):
        """前の仕訳がずれて一覧が残っていたら、次の仕訳を打つ前に止まる。"""
        win = FakeWin()
        runner, ctl, sender, messages = make_runner(self.cfg, win)
        original_paste = sender.paste

        def paste(text):
            original_paste(text)
            if text == "振込" and "[B]" not in sender.text():
                win.fg = (3, "元帳摘要一覧", 100)   # 1件目の最後で、一覧が閉じなかったことにする
        sender.paste = paste
        press_resume_later(ctl, delay=0.8, before=ctl.cancel)
        with self.assertRaises(z.Cancelled):
            self.run_rows(runner)
        self.assertNotIn("[B]", sender.text())
        self.assertTrue(any("ずれた可能性" in m for m in messages), messages)


class ProgressTest(unittest.TestCase):
    """どこまで入力したかの記録。CSV が途中で変わっても、二重に入力したり飛ばしたりしないこと。"""

    LINES = ["2026/01/05,9411,1113,100,0,,A,振込,", "2026/01/06,9411,1113,200,0,,B,振込,",
             "2026/01/07,9411,1113,300,0,,C,振込,", "2026/02/03,9411,1113,400,0,,D,振込,"]

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.record = self.dir / "記録.json"

    def enter(self, lines, count=None):
        """1月分を入力する。count を指定すると、その件数を入れたところで中止する。戻り値は入力した取引先名。"""
        cfg, groups = load(write_csv(self.dir, lines))
        rows = groups[(2026, 1)]
        progress = z.Progress(self.record, "2026-01")
        start, problem = progress.resolve(rows)
        if problem:
            return problem
        runner, ctl, sender, _ = make_runner(cfg)
        done = []

        def on_row_done(n, total):
            done.append(n)
            if count and len(done) == count:
                ctl.cancel()
        try:
            runner.run_rows(rows, start, progress, notify=lambda m: None, log_file=self.dir / "log.txt",
                            on_row_done=on_row_done)
        except z.Cancelled:
            pass
        return [s[1:-1] for s in sender.sent if s.startswith("[") and s[1:-1] in "ABCDX"]

    def test_resume_continues_after_last_entered_row(self):
        self.assertEqual(self.enter(self.LINES, count=2), ["A", "B"])
        self.assertEqual(self.enter(self.LINES), ["C"])
        self.assertEqual(self.enter(self.LINES), [])

    def test_row_inserted_before_month_does_not_duplicate(self):
        """入力の途中で、CSV の上の方に行が増えて行番号がずれても、続きから正しく入力する。"""
        self.assertEqual(self.enter(self.LINES, count=2), ["A", "B"])
        shifted = ["2025/12/30,9411,1113,50,0,,X,振込,", *self.LINES]
        self.assertEqual(self.enter(shifted), ["C"])

    def test_row_added_after_entered_rows_is_entered(self):
        self.assertEqual(self.enter(self.LINES, count=2), ["A", "B"])
        added = [*self.LINES[:2], "2026/01/06,9411,1113,250,0,,X,振込,", *self.LINES[2:]]
        self.assertEqual(self.enter(added), ["X", "C"])

    def test_changed_entered_row_is_blocked(self):
        """入力済みの仕訳の金額が CSV で変わっていたら、続きを入力せずに止める。"""
        self.assertEqual(self.enter(self.LINES, count=2), ["A", "B"])
        changed = [self.LINES[0].replace(",100,", ",999,"), *self.LINES[1:]]
        self.assertIn("変わっています", self.enter(changed))

    def test_old_record_with_line_number_only_still_works(self):
        self.record.write_text('{"last_completed_line": 3, "in_progress_line": null}', encoding="utf-8")
        self.assertEqual(self.enter(self.LINES), ["C"])


if __name__ == "__main__":
    unittest.main()

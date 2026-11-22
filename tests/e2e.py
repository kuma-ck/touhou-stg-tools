# /// script
# requires-python = ">=3.10"
# dependencies = ["playwright>=1.40"]
# ///
"""E2E テスト: ローカルに HTTP サーバーを立て、実際のブラウザで 3 ページを操作する。

    uv run tests/e2e.py

ブラウザは Microsoft Edge（Windows には標準で入っている）を使う。
Edge がない環境では先に `uv run --with playwright playwright install chromium` を実行する。
Google Fonts への通信は空の CSS で置き換えるので、オフラインでも動く。
"""

from __future__ import annotations

import functools
import json
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import Browser, Page, expect, sync_playwright

REPO = Path(__file__).resolve().parent.parent
GAMES = json.loads((REPO / "data" / "games.json").read_text(encoding="utf-8"))["games"]
GI = {g["id"]: g for g in GAMES}
LOCAL_KEY = "touhou-stg-tools:clear-tracker:v1"
LIGHT_BG, DARK_BG = "rgb(243, 244, 249)", "rgb(10, 11, 17)"


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class E2E(unittest.TestCase):
    browser: Browser
    base: str

    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(REPO)))
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(channel="msedge")
        except Exception:
            cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()

    def open(self, path: str, *, scheme: str = "light", width: int = 1100, height: int = 900) -> Page:
        """新しいコンテキスト（localStorage は空）でページを開く。コンソールのエラーは記録して最後に確かめる。"""
        ctx = self.browser.new_context(color_scheme=scheme, viewport={"width": width, "height": height})
        self.addCleanup(ctx.close)
        ctx.route("https://fonts.googleapis.com/**", lambda r: r.fulfill(status=200, content_type="text/css", body=""))
        ctx.route("https://fonts.gstatic.com/**", lambda r: r.abort())
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error" and "fonts.gstatic.com" not in m.text and errors.append(m.text))
        self.addCleanup(lambda: self.assertEqual(errors, [], f"{path} でエラーが出ました"))
        page.goto(self.base + path)
        return page

    def bg(self, page: Page) -> str:
        return page.evaluate("getComputedStyle(document.body).backgroundColor")

    def assert_no_horizontal_scroll(self, page: Page):
        sw, iw = page.evaluate("[document.documentElement.scrollWidth, innerWidth]")
        self.assertLessEqual(sw, iw, "横スクロールが出ています")

    # ---------- トップページ ----------

    def test_top_page(self):
        page = self.open("/")
        expect(page).to_have_title("touhou-stg-tools")
        expect(page.locator(".tool")).to_have_count(3)
        expect(page.locator("style#design")).to_have_count(1)
        expect(page.locator(".chip.accent")).to_have_text("公開中")
        self.assertEqual(self.bg(page), LIGHT_BG)
        page.get_by_role("link", name="デザインの見本").click()
        expect(page).to_have_url(self.base + "/design/")
        page.go_back()
        page.locator("a.tool").click()
        expect(page.locator("h1")).to_have_text("東方クリア表")

    def test_top_page_follows_dark_mode(self):
        page = self.open("/", scheme="dark")
        self.assertEqual(self.bg(page), DARK_BG)

    # ---------- デザインの見本 ----------

    def test_design_page_renders_tokens_and_games(self):
        page = self.open("/design/")
        expect(page.locator("#colors .sw")).to_have_count(17)
        expect(page.locator("#colors .sw .hex").first).to_have_text("#f3f4f9")
        expect(page.locator("#hues .hue")).to_have_count(len(GAMES))
        expect(page.locator("#space > div")).to_have_count(7)

    def test_design_page_theme_switch(self):
        page = self.open("/design/", scheme="dark")
        html = page.locator("html")
        self.assertEqual(self.bg(page), DARK_BG)
        page.get_by_role("radio", name="ライト").click()
        expect(html).to_have_attribute("data-theme", "light")
        self.assertEqual(self.bg(page), LIGHT_BG)
        expect(page.locator("#colors .sw .hex").first).to_have_text("#f3f4f9")
        page.get_by_role("radio", name="ダーク").click()
        expect(html).to_have_attribute("data-theme", "dark")
        self.assertEqual(self.bg(page), DARK_BG)
        expect(page.locator("#colors .sw .hex").first).to_have_text("#0a0b11")
        page.get_by_role("radio", name="自動").click()
        self.assertIsNone(html.get_attribute("data-theme"))
        expect(page.get_by_role("radio", name="自動")).to_have_attribute("aria-checked", "true")

    def test_design_page_demo_controls(self):
        page = self.open("/design/")
        tog = page.locator("#demoTogs .tog").nth(1)
        expect(tog).to_have_attribute("aria-pressed", "false")
        tog.click()
        expect(tog).to_have_attribute("aria-pressed", "true")
        page.locator("#demoSeg button", has_text="クリア").click()
        expect(page.locator("#demoSeg [aria-checked=true]")).to_have_text("クリア")

    # ---------- 東方クリア表 ----------

    def stored(self, page: Page) -> dict:
        return page.evaluate(f"JSON.parse(localStorage.getItem({LOCAL_KEY!r}) || 'null')")

    def wait_saved(self, page: Page, gid: str, key: str):
        page.wait_for_function(
            f"(() => {{ const j = JSON.parse(localStorage.getItem({LOCAL_KEY!r}) || 'null');"
            f" return !!(j && j.games[{gid!r}] && j.games[{gid!r}].cells[{key!r}]); }})()")

    def test_tracker_overview(self):
        page = self.open("/clear-tracker/")
        expect(page.locator(".gcard")).to_have_count(len(GAMES))
        expect(page.locator(".brow")).to_have_count(5)
        expect(page.locator(".notice")).to_contain_text("このブラウザに保存されます")
        expect(page.locator(".recent")).to_have_count(0)

    def test_tracker_record_no_continue_and_persist(self):
        g = GI["th08"]
        page = self.open("/clear-tracker/")
        page.locator(".gcard", has_text=g["title"]).click()
        expect(page).to_have_url(self.base + "/clear-tracker/#th08")
        expect(page.locator(".ghead h1")).to_have_text(g["title"])
        expect(page.locator(".cell")).to_have_count(len(g["shots"]) * len(g["difficulties"]))

        shot = g["shots"][0]
        cell = page.locator(f'.cell[data-s="{shot}"][data-d="L"]')
        cell.click()
        sheet = page.get_by_role("dialog")
        expect(sheet).to_be_visible()
        expect(sheet.locator("#shT")).to_have_text(shot)
        sheet.get_by_role("radio", name="ノーコン").click()
        expect(sheet.get_by_role("radio", name="ノーコン")).to_have_attribute("aria-checked", "true")
        sheet.locator("#fNote").fill("6面で2ボム")
        sheet.get_by_role("button", name="完了").click()
        expect(sheet).to_have_count(0)
        expect(cell).to_have_class("cell t2")
        expect(cell).to_have_text("1cc")

        self.wait_saved(page, "th08", f"{shot}|L")
        # 書きかけのメモは「完了」で日時付きの 1 件として保存される
        page.wait_for_function(f"(JSON.parse(localStorage.getItem({LOCAL_KEY!r})).games.th08.cells[{f'{shot}|L'!r}].notes || []).length === 1")
        rec = self.stored(page)["games"]["th08"]["cells"][f"{shot}|L"]
        self.assertTrue(rec["c"] and rec["cc"])
        self.assertRegex(rec["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(rec["dates"], {"c": rec["date"], "cc": rec["date"]})
        self.assertEqual(rec["notes"][0]["text"], "6面で2ボム")
        self.assertRegex(rec["notes"][0]["at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
        self.assertTrue(rec["note"].endswith(" 6面で2ボム"), rec["note"])  # 旧形式・CSV 用の文字列

        page.reload()
        expect(page.locator(f'.cell[data-s="{shot}"][data-d="L"]')).to_have_class("cell t2")
        page.get_by_role("link", name="作品一覧").click()
        expect(page.locator(".recent li")).to_have_count(1)
        expect(page.locator(".recent .chip")).to_have_text("1cc")
        expect(page.locator(".recent .chip")).to_have_class("chip t2")

    def test_tracker_nmnb_implies_lower_levels(self):
        page = self.open("/clear-tracker/#th06")
        cell = page.locator('.cell[data-s="霊夢A"][data-d="N"]')
        cell.click()
        sheet = page.get_by_role("dialog")
        sheet.get_by_role("button", name="ノーミスノーボム").click()
        for name in ("ノーボム", "ノーミス", "ノーミスノーボム"):
            expect(sheet.get_by_role("button", name=name, exact=True)).to_have_attribute("aria-pressed", "true")
        expect(sheet.get_by_role("radio", name="ノーコン")).to_have_attribute("aria-checked", "true")
        sheet.get_by_role("button", name="完了").click()
        expect(cell).to_have_class("cell t4")
        expect(cell).to_have_text("NMNB")
        self.wait_saved(page, "th06", "霊夢A|N")
        rec = self.stored(page)["games"]["th06"]["cells"]["霊夢A|N"]
        self.assertTrue(all(rec.get(k) for k in ("c", "cc", "nb", "nm", "nmnb")), rec)

    def test_tracker_extra_uses_ex_shots_and_saves_clear_as_cc(self):
        g = GI["th16"]
        page = self.open("/clear-tracker/#th16")
        expect(page.locator(".subh")).to_have_text("EXTRA")
        expect(page.locator('.cell[data-d="Ex"]')).to_have_count(len(g["exShots"]))
        expect(page.locator('.cell[data-d="E"]')).to_have_count(len(g["shots"]))
        shot = g["exShots"][0]
        page.locator(f'.cell[data-s="{shot}"][data-d="Ex"]').click()
        sheet = page.get_by_role("dialog")
        expect(sheet.get_by_role("radio")).to_have_count(2)  # Extra にはノーコンの選択肢がない
        sheet.get_by_role("radio", name="クリア").click()
        sheet.get_by_role("button", name="完了").click()
        self.wait_saved(page, "th16", f"{shot}|Ex")
        rec = self.stored(page)["games"]["th16"]["cells"][f"{shot}|Ex"]
        self.assertTrue(rec["c"] and rec["cc"], rec)
        expect(page.locator(f'.cell[data-s="{shot}"][data-d="Ex"]')).to_have_text("Clear")

    def sheet_for(self, page: Page, shot: str, diff: str):
        page.locator(f'.cell[data-s="{shot}"][data-d="{diff}"]').click()
        sheet = page.get_by_role("dialog")
        expect(sheet).to_be_visible()
        return sheet

    def cell_rec(self, page: Page, gid: str, key: str) -> dict:
        return (self.stored(page) or {"games": {}})["games"].get(gid, {}).get("cells", {}).get(key)

    def wait_rec(self, page: Page, gid: str, key: str, pred):
        """保存が終わり、セルの記録が条件を満たすまで待つ（localStorage へは少し遅れて書かれる）。"""
        page.wait_for_timeout(50)
        for _ in range(40):
            rec = self.cell_rec(page, gid, key)
            if rec is not None and pred(rec):
                return rec
            page.wait_for_timeout(50)
        self.fail(f"{gid} {key} の記録が期待どおりになりません: {self.cell_rec(page, gid, key)}")

    def test_tracker_dates_are_kept_per_achievement(self):
        page = self.open("/clear-tracker/")
        page.clock.set_fixed_time("2026-11-02T12:00:00")
        page.goto(self.base + "/clear-tracker/#th08")
        key = "幽冥組|N"
        sheet = self.sheet_for(page, "幽冥組", "N")
        expect(sheet.locator("#dateRows .hint")).to_contain_text("到達や縛りを選ぶと")
        sheet.get_by_role("radio", name="クリア").click()
        self.wait_rec(page, "th08", key, lambda r: r.get("dates") == {"c": "2026-11-02"})
        sheet.get_by_role("button", name="完了").click()

        # 後日ノーコンと Final B を達成しても、クリアの日付は残る
        page.clock.set_fixed_time("2026-11-22T12:00:00")
        sheet = self.sheet_for(page, "幽冥組", "N")
        sheet.get_by_role("radio", name="ノーコン").click()
        sheet.get_by_role("button", name="Final B").click()
        rec = self.wait_rec(page, "th08", key, lambda r: "x:Final B" in r.get("dates", {}))
        self.assertEqual(rec["dates"], {"c": "2026-11-02", "cc": "2026-11-22", "x:Final B": "2026-11-22"})
        self.assertEqual(rec["date"], "2026-11-22")  # 旧形式用は最新の達成日
        expect(sheet.locator(".drow")).to_have_count(3)
        expect(sheet.locator('[data-dk="c"]')).to_have_value("2026-11-02")

        # 日付は 1 件ずつ直せる
        sheet.locator('[data-dk="cc"]').fill("2026-11-10")
        self.wait_rec(page, "th08", key, lambda r: r["dates"].get("cc") == "2026-11-10")

        # 未に戻して選び直すと、元の日付に戻る
        sheet.get_by_role("radio", name="未").click()
        rec = self.wait_rec(page, "th08", key, lambda r: not r.get("c"))
        self.assertEqual(rec.get("dates"), {"x:Final B": "2026-11-22"})
        sheet.get_by_role("radio", name="ノーコン").click()
        rec = self.wait_rec(page, "th08", key, lambda r: r.get("cc"))
        self.assertEqual(rec["dates"], {"c": "2026-11-02", "cc": "2026-11-10", "x:Final B": "2026-11-22"})
        sheet.get_by_role("button", name="完了").click()

        # 最近の達成は達成した日ごとに並ぶ
        page.get_by_role("link", name="作品一覧").click()
        items = page.locator(".recent li")
        expect(items).to_have_count(3)
        expect(items.nth(0)).to_contain_text("Final B")
        expect(items.nth(1)).to_contain_text("2026-11-10")
        expect(items.nth(1).locator(".chip")).to_have_text("1cc")
        expect(items.nth(2).locator(".chip")).to_have_text("Clear")

    def test_tracker_memos_are_separate_entries(self):
        page = self.open("/clear-tracker/")
        page.clock.set_fixed_time("2026-11-02T21:30:00")
        page.goto(self.base + "/clear-tracker/#th06")
        key = "霊夢A|H"
        sheet = self.sheet_for(page, "霊夢A", "H")
        save = sheet.get_by_role("button", name="メモを保存")
        expect(save).to_be_disabled()
        sheet.locator("#fNote").fill("初クリア 残1")
        save.click()
        expect(sheet.locator("#fNote")).to_have_value("")
        page.clock.set_fixed_time("2026-11-22T20:05:00")
        sheet.locator("#fNote").fill("2回目")
        sheet.locator("#fNote").press("Control+Enter")
        rec = self.wait_rec(page, "th06", key, lambda r: len(r.get("notes", [])) == 2)
        self.assertEqual([(n["at"], n["text"]) for n in rec["notes"]],
                         [("2026-11-02T21:30", "初クリア 残1"), ("2026-11-22T20:05", "2回目")])
        notes = sheet.locator(".note")
        expect(notes.nth(0)).to_contain_text("2026/11/22 20:05")  # 新しい順
        expect(notes.nth(1)).to_contain_text("初クリア 残1")

        # 編集しても書いた日時は変わらず、編集日時が付く
        notes.nth(1).get_by_role("button", name="編集").click()
        sheet.locator("[data-edit]").fill("初クリア 残2")
        sheet.get_by_role("button", name="保存", exact=True).click()
        rec = self.wait_rec(page, "th06", key, lambda r: r["notes"][0]["text"] == "初クリア 残2")
        self.assertEqual(rec["notes"][0]["at"], "2026-11-02T21:30")
        self.assertEqual(rec["notes"][0]["edited"], "2026-11-22T20:05")
        expect(notes.nth(1)).to_contain_text("編集")

        # 削除は確かめてから
        notes.nth(0).get_by_role("button", name="削除", exact=True).click()
        expect(sheet.locator(".nconf")).to_contain_text("このメモを削除しますか")
        sheet.get_by_role("button", name="削除する").click()
        expect(notes).to_have_count(1)
        rec = self.wait_rec(page, "th06", key, lambda r: len(r["notes"]) == 1)
        self.assertEqual(rec["note"], "2026/11/02 21:30 初クリア 残2")
        # 到達を記録していなくても、メモだけのマスは残る
        self.assertNotIn("c", rec)
        sheet.get_by_role("button", name="完了").click()
        expect(page.locator('.cell[data-s="霊夢A"][data-d="H"] .dot')).to_have_count(1)

    def test_tracker_reads_old_note_format(self):
        page = self.open("/clear-tracker/")
        old = {"version": 1, "games": {"th08": {"cells": {"紅魔組|E": {
            "c": True, "cc": True, "date": "2025-05-05", "note": "古いメモ\n2026/11/22 Final B 残2"}},
            "hidden": {"shots": [], "diffs": []}, "skip": False}}}
        page.evaluate(f"localStorage.setItem({LOCAL_KEY!r}, {json.dumps(json.dumps(old, ensure_ascii=False), ensure_ascii=False)})")
        page.goto(self.base + "/clear-tracker/#th08")
        page.reload()  # ハッシュだけの移動では読み直さないので、保存した記録を読ませる
        sheet = self.sheet_for(page, "紅魔組", "E")
        notes = sheet.locator(".note")
        expect(notes).to_have_count(2)
        expect(notes.nth(0)).to_contain_text("2026/11/22")
        expect(notes.nth(0)).to_contain_text("Final B 残2")
        expect(notes.nth(1)).to_contain_text("以前のメモ")
        # 旧形式の日付は最初の達成（クリア）の日付として出す
        expect(sheet.locator('[data-dk="c"]')).to_have_value("2025-05-05")
        expect(sheet.locator('[data-dk="cc"]')).to_have_value("")

    def test_tracker_dark_mode(self):
        page = self.open("/clear-tracker/#th08", scheme="dark")
        self.assertEqual(self.bg(page), DARK_BG)

    # ---------- スマホ幅 ----------

    def test_phone_width_has_no_horizontal_scroll(self):
        for path in ("/", "/design/", "/clear-tracker/", "/clear-tracker/#th19"):
            with self.subTest(path=path):
                page = self.open(path, width=375, height=812)
                page.wait_for_load_state("networkidle")
                self.assert_no_horizontal_scroll(page)

    def test_phone_width_sheet_fits(self):
        page = self.open("/clear-tracker/#th08", width=375, height=812)
        page.locator(".cell").first.click()
        box = page.get_by_role("dialog").bounding_box()
        self.assertIsNotNone(box)
        self.assertLessEqual(box["x"] + box["width"], 375)
        expect(page.get_by_role("button", name="完了")).to_be_in_viewport()


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""scripts/ の単体テスト（標準ライブラリの unittest のみ）。

    uv run python -m unittest discover -s tests -v
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import export_artifact  # noqa: E402
import sync_data  # noqa: E402


def game(**over):
    g = {"id": "th06", "no": "06", "title": "東方紅魔郷", "year": 2002, "hue": 352,
         "difficulties": ["E", "N", "H", "L", "Ex"], "shots": ["霊夢A", "霊夢B"]}
    g.update(over)
    return g


def games_doc(*games):
    return {"difficultyNames": {d: d for d in sync_data.DIFFICULTIES}, "games": list(games) or [game()]}


TOKENS = """/* 説明 */
:root{
  --bg:#fff; /* 地 */
  --ink:#000;
  --accent:#55f;
}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#000; --ink:#fff;
  color-scheme:dark;
}}
"""
COMPONENTS = """/* 部品 */
.card{background:var(--bg);color:var(--ink)}
.ring{--p:0;background:conic-gradient(var(--accent) calc(var(--p)*1%),var(--line,#ccc) 0)}
"""


class DumpTest(unittest.TestCase):
    def test_scalar_lists_stay_on_one_line(self):
        self.assertEqual(sync_data.dump({"a": [1, "二"], "b": {}}), '{\n  "a": [1, "二"],\n  "b": {}\n}')

    def test_nested_lists_are_expanded(self):
        self.assertEqual(sync_data.dump([{"x": 1}]), '[\n  {\n    "x": 1\n  }\n]')

    def test_round_trip_keeps_data(self):
        doc = json.loads((REPO / "data" / "games.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(sync_data.dump(doc)), doc)


class ValidateGamesTest(unittest.TestCase):
    def check(self, doc):
        return sync_data.validate_games(doc)

    def test_repository_data_is_valid(self):
        doc = json.loads((REPO / "data" / "games.json").read_text(encoding="utf-8"))
        self.assertEqual(self.check(doc), [])

    def test_valid_minimal(self):
        self.assertEqual(self.check(games_doc()), [])

    def test_empty_games(self):
        self.assertEqual(len(self.check({"games": []})), 1)

    def test_missing_required_and_unknown_key(self):
        g = game(color="red")
        del g["year"]
        errors = self.check(games_doc(g))
        self.assertTrue(any("必須項目" in e and "year" in e for e in errors), errors)
        self.assertTrue(any("未知の項目" in e and "color" in e for e in errors), errors)

    def test_duplicate_id(self):
        self.assertTrue(any("重複" in e for e in self.check(games_doc(game(), game()))))

    def test_unknown_difficulty(self):
        self.assertTrue(any("不明な難易度" in e for e in self.check(games_doc(game(difficulties=["N", "X"])))))

    def test_duplicate_and_empty_shots(self):
        self.assertTrue(any("shots に重複" in e for e in self.check(games_doc(game(shots=["A", "A"])))))
        self.assertTrue(any("flags が空" in e for e in self.check(games_doc(game(flags=[])))))

    def test_ex_shots_need_extra(self):
        g = game(difficulties=["E", "N"], exShots=["A"])
        self.assertTrue(any("exShots" in e for e in self.check(games_doc(g))))

    def test_hue_range_and_type(self):
        for hue in (-1, 360, "200", 12.5, True, None):
            with self.subTest(hue=hue):
                self.assertTrue(any("hue" in e for e in self.check(games_doc(game(hue=hue)))))
        self.assertEqual(self.check(games_doc(game(hue=0))), [])
        self.assertEqual(self.check(games_doc(game(hue=359))), [])

    def test_remake_of_must_exist(self):
        ok = games_doc(game(), game(id="nc06", remakeOf="th06"))
        bad = games_doc(game(id="nc06", remakeOf="th99"))
        self.assertEqual(self.check(ok), [])
        self.assertTrue(any("remakeOf" in e for e in self.check(bad)))


class BlockTest(unittest.TestCase):
    def test_escapes_closing_tags(self):
        out = sync_data.block("games", {"t": "</script><b>"})
        self.assertNotIn("</script><b>", out)
        self.assertIn("<\\/script>", out)
        payload = out.split(">", 2)[2].rsplit("</script>", 1)[0].split('id="data-games">', 1)[-1]
        self.assertEqual(json.loads(payload.replace("<\\/", "</")), {"t": "</script><b>"})

    def test_markers(self):
        out = sync_data.block("games", {})
        self.assertTrue(out.startswith("<!-- data:games:begin -->"))
        self.assertTrue(out.endswith("<!-- data:games:end -->"))


class ValidateDesignTest(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(sync_data.validate_design(TOKENS, COMPONENTS), [])

    def test_repository_design_is_valid(self):
        d = REPO / "design"
        self.assertEqual(sync_data.validate_design((d / "tokens.css").read_text(encoding="utf-8"),
                                                   (d / "components.css").read_text(encoding="utf-8")), [])

    def test_missing_dark_block(self):
        tokens = TOKENS.split("@media")[0]
        self.assertTrue(any("2 ブロック" in e for e in sync_data.validate_design(tokens, COMPONENTS)))

    def test_hand_written_selected_dark_block_is_rejected(self):
        tokens = TOKENS + ':root[data-theme="dark"]{--bg:#000}\n'
        self.assertTrue(any("data-theme" in e for e in sync_data.validate_design(tokens, COMPONENTS)))

    def test_selector_inside_comment_is_ignored(self):
        tokens = '/* :root[data-theme="dark"] は自動で作る */\n' + TOKENS
        self.assertEqual(sync_data.validate_design(tokens, COMPONENTS), [])

    def test_dark_only_token(self):
        tokens = TOKENS.replace("--bg:#000;", "--bg:#000; --new:#123;")
        errors = sync_data.validate_design(tokens, COMPONENTS)
        self.assertTrue(any("--new" in e for e in errors), errors)

    def test_undefined_token_in_components(self):
        errors = sync_data.validate_design(TOKENS, COMPONENTS + ".x{color:var(--nope)}")
        self.assertTrue(any("--nope" in e for e in errors), errors)

    def test_fallback_and_local_definitions_are_allowed(self):
        # --line は既定値つき、--p は components.css 内で定義されている
        self.assertEqual(sync_data.validate_design(TOKENS, COMPONENTS), [])

    def test_closing_style_tag_is_rejected(self):
        for tokens, components in ((TOKENS + "/* </style> */", COMPONENTS), (TOKENS, COMPONENTS + "/* </STYLE> */")):
            with self.subTest(tokens=tokens[-12:], components=components[-12:]):
                errors = sync_data.validate_design(tokens, components)
                self.assertTrue(any("</style>" in e for e in errors), errors)


class ValidatePageTokensTest(unittest.TestCase):
    def page(self, css, extra=""):
        return f"<head><!-- design:begin --><style>.z{{color:var(--from-region)}}</style><!-- design:end --><style>{css}</style></head><body>{extra}</body>"

    def test_defined_tokens_pass(self):
        html = self.page(".a{color:var(--accent);padding:var(--p)} .b{--p:1}")
        self.assertEqual(sync_data.validate_page_tokens("x.html", html, TOKENS, COMPONENTS), [])

    def test_undefined_token_fails(self):
        html = self.page(".a{color:var(--typo)}")
        errors = sync_data.validate_page_tokens("x.html", html, TOKENS, COMPONENTS)
        self.assertEqual(len(errors), 1)
        self.assertIn("--typo", errors[0])
        self.assertIn("x.html", errors[0])

    def test_value_set_from_inline_style_or_js_counts(self):
        html = self.page(".hue{color:hsl(var(--h) 50% 50%)}", '<script>el.innerHTML=`<i style="--h:${h}">`</script>')
        self.assertEqual(sync_data.validate_page_tokens("x.html", html, TOKENS, COMPONENTS), [])

    def test_design_region_is_not_checked(self):
        self.assertEqual(sync_data.validate_page_tokens("x.html", self.page(""), TOKENS, COMPONENTS), [])

    def test_repository_pages_pass(self):
        d = REPO / "design"
        tokens = (d / "tokens.css").read_text(encoding="utf-8")
        components = (d / "components.css").read_text(encoding="utf-8")
        for rel in sync_data.DESIGN_TARGETS:
            with self.subTest(rel=rel):
                html = (REPO / rel).read_text(encoding="utf-8")
                self.assertEqual(sync_data.validate_page_tokens(rel, html, tokens, components), [])


class DesignBlockTest(unittest.TestCase):
    def setUp(self):
        self.out = sync_data.design_block("<link rel=x>\n", TOKENS, COMPONENTS)

    def test_markers_and_order(self):
        self.assertTrue(self.out.startswith("<!-- design:begin -->\n<link rel=x>\n<style id=\"design\">"))
        self.assertTrue(self.out.endswith("</style>\n<!-- design:end -->"))
        self.assertLess(self.out.index("--accent:#55f"), self.out.index('[data-theme="dark"]'))
        self.assertLess(self.out.index('[data-theme="dark"]'), self.out.index(".card{"))

    def test_selected_dark_block_copies_media_block(self):
        media = sync_data.DARK.search(TOKENS).group(1)
        self.assertIn(f':root[data-theme="dark"]{{{media}}}', self.out)

    def test_single_style_element(self):
        self.assertEqual(self.out.count("<style"), 1)
        self.assertEqual(self.out.count("</style>"), 1)


class MainTest(unittest.TestCase):
    """一時ディレクトリにリポジトリの最小構成を作り、main() を通しで動かす。"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "data").mkdir()
        (self.tmp / "design").mkdir()
        (self.tmp / "tool").mkdir()
        (self.tmp / "data" / "games.json").write_text(sync_data.dump(games_doc()) + "\n", encoding="utf-8")
        (self.tmp / "design" / "fonts.html").write_text("<link rel=x>\n", encoding="utf-8")
        (self.tmp / "design" / "tokens.css").write_text(TOKENS, encoding="utf-8")
        (self.tmp / "design" / "components.css").write_text(COMPONENTS, encoding="utf-8")
        self.page = self.tmp / "tool" / "index.html"
        self.page.write_text("<head>\n<!-- design:begin -->\n<!-- design:end -->\n<style>.a{color:var(--ink)}</style>\n</head>\n"
                             "<body>\n<!-- data:games:begin -->\n<!-- data:games:end -->\n</body>\n", encoding="utf-8")
        patches = [
            mock.patch.object(sync_data, "ROOT", self.tmp),
            mock.patch.object(sync_data, "DATA", self.tmp / "data"),
            mock.patch.object(sync_data, "DESIGN", self.tmp / "design"),
            mock.patch.object(sync_data, "TARGETS", {"games": ["tool/index.html"]}),
            mock.patch.object(sync_data, "DESIGN_TARGETS", ["tool/index.html"]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "argv", ["sync_data.py", *args]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sync_data.main()
        return code, out.getvalue(), err.getvalue()

    def test_check_reports_stale_without_writing(self):
        before = self.page.read_bytes()
        code, out, _ = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("tool/index.html", out)
        self.assertEqual(self.page.read_bytes(), before)

    def test_sync_then_check_is_clean(self):
        self.assertEqual(self.run_main()[0], 0)
        html = self.page.read_text(encoding="utf-8")
        self.assertIn('<style id="design">', html)
        self.assertIn('id="data-games"', html)
        self.assertIn(':root[data-theme="dark"]', html)
        code, out, _ = self.run_main("--check")
        self.assertEqual((code, out.strip()), (0, "変更はありません"))

    def test_writes_lf_line_endings(self):
        self.run_main()
        self.assertNotIn(b"\r\n", self.page.read_bytes())

    def test_stale_file_listed_once(self):
        code, out, _ = self.run_main("--check")
        self.assertEqual(out.count("tool/index.html"), 1)

    def test_reformats_games_json(self):
        (self.tmp / "data" / "games.json").write_text(json.dumps(games_doc()), encoding="utf-8")
        code, out, _ = self.run_main("--check")
        self.assertEqual(code, 1)
        self.assertIn("data/games.json", out)

    def test_design_error_writes_nothing(self):
        (self.tmp / "data" / "games.json").write_text(json.dumps(games_doc()), encoding="utf-8")
        (self.tmp / "design" / "components.css").write_text(COMPONENTS + ".x{color:var(--nope)}", encoding="utf-8")
        before = {p: p.read_bytes() for p in (self.page, self.tmp / "data" / "games.json")}
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("--nope", err)
        for p, b in before.items():
            self.assertEqual(p.read_bytes(), b, p)

    def test_games_error_exit_2(self):
        (self.tmp / "data" / "games.json").write_text(json.dumps(games_doc(game(hue=999))), encoding="utf-8")
        code, _, err = self.run_main("--check")
        self.assertEqual(code, 2)
        self.assertIn("hue", err)

    def test_missing_region_exit_2(self):
        self.page.write_text("<head></head><body><!-- data:games:begin --><!-- data:games:end --></body>", encoding="utf-8")
        code, _, err = self.run_main()
        self.assertEqual(code, 2)
        self.assertIn("design の埋め込み区間がありません", err)

    def test_undefined_token_in_page_exit_2(self):
        self.page.write_text(self.page.read_text(encoding="utf-8").replace("var(--ink)", "var(--inc)"), encoding="utf-8")
        code, _, err = self.run_main("--check")
        self.assertEqual(code, 2)
        self.assertIn("--inc", err)


class RepositoryIsInSyncTest(unittest.TestCase):
    def test_check_passes(self):
        out = io.StringIO()
        with mock.patch.object(sys, "argv", ["sync_data.py", "--check"]), contextlib.redirect_stdout(out):
            self.assertEqual(sync_data.main(), 0, out.getvalue())


class ExportArtifactTest(unittest.TestCase):
    def test_strips_document_shell_and_meta(self):
        html = ('<!doctype html>\n<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
                '<meta name="viewport" content="width=device-width">\n<title>T</title>\n'
                '<meta name="claude:viewport-fit-sides" content="cover">\n</head>\n<body class="x">\n<p>本文</p>\n</body>\n</html>\n')
        out = export_artifact.to_artifact(html)
        self.assertEqual(out, '<title>T</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n\n<p>本文</p>\n')

    def test_requires_head_and_body(self):
        with self.assertRaises(ValueError):
            export_artifact.to_artifact("<p>no head</p>")

    def test_real_tool_keeps_design_and_data(self):
        out = export_artifact.to_artifact((REPO / "clear-tracker" / "index.html").read_text(encoding="utf-8"))
        self.assertIn('<style id="design">', out)
        self.assertIn('id="data-games"', out)
        self.assertNotIn("<head>", out)
        self.assertNotIn('name="viewport"', out)


if __name__ == "__main__":
    unittest.main()

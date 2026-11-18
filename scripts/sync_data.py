# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""data/ の共通データと design/ のデザインシステムを検証し、各ツールの HTML に埋め込む。

各ツールは 1 ファイルで完結する HTML にしている（GitHub Pages でも Claude の
アーティファクトでもそのまま動かすため）。共通データは HTML 内の

    <!-- data:games:begin -->
    <script type="application/json" id="data-games">...</script>
    <!-- data:games:end -->

の区間に、デザインシステム（design/fonts.html・tokens.css・components.css）は

    <!-- design:begin -->
    <link ...フォント...>
    <style id="design">...</style>
    <!-- design:end -->

の区間に埋め込む。data/ や design/ を直したら、このスクリプトを実行する。

使い方:
    uv run scripts/sync_data.py          # 整形・検証して埋め込みを更新
    uv run scripts/sync_data.py --check  # 更新が必要なら終了コード 1（CI 用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DESIGN = ROOT / "design"

# 埋め込み先: データ名 -> そのデータを使う HTML
TARGETS: dict[str, list[str]] = {
    "games": ["clear-tracker/index.html", "design/index.html"],
}

# デザインシステムの埋め込み先（<head> 内、各ツール固有の <style> より前に置く）
DESIGN_TARGETS: list[str] = [
    "index.html",
    "clear-tracker/index.html",
    "design/index.html",
]
DESIGN_CSS = ["tokens.css", "components.css"]

DIFFICULTIES = {"E", "N", "H", "L", "Ex", "Ph"}
GAME_KEYS = {"id", "no", "title", "titleEn", "year", "remakeOf", "hue",
             "difficulties", "shots", "exShots", "flags"}
REQUIRED = {"id", "no", "title", "year", "hue", "difficulties", "shots"}


def dump(obj, indent: int = 2, level: int = 0) -> str:
    """スカラーだけの配列は 1 行にまとめる JSON 整形（差分を読みやすくするため）。"""
    pad, inner = " " * (indent * level), " " * (indent * (level + 1))
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items = [f"{inner}{json.dumps(k, ensure_ascii=False)}: {dump(v, indent, level + 1)}"
                 for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(obj, list):
        if all(not isinstance(v, (dict, list)) for v in obj):
            return "[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in obj) + "]"
        return "[\n" + ",\n".join(inner + dump(v, indent, level + 1) for v in obj) + "\n" + pad + "]"
    return json.dumps(obj, ensure_ascii=False)


def validate_games(doc: dict) -> list[str]:
    errors: list[str] = []
    games = doc.get("games")
    if not isinstance(games, list) or not games:
        return ["games が空、または配列ではありません"]
    names = doc.get("difficultyNames", {})
    seen: set[str] = set()
    for i, g in enumerate(games):
        where = f"games[{i}] ({g.get('id', '?')})"
        missing = REQUIRED - g.keys()
        if missing:
            errors.append(f"{where}: 必須項目がありません: {sorted(missing)}")
        unknown = g.keys() - GAME_KEYS
        if unknown:
            errors.append(f"{where}: 未知の項目があります: {sorted(unknown)}")
        gid = g.get("id")
        if gid in seen:
            errors.append(f"{where}: id が重複しています")
        seen.add(gid)
        for d in g.get("difficulties", []):
            if d not in DIFFICULTIES or d not in names:
                errors.append(f"{where}: 不明な難易度 {d!r}")
        for key in ("shots", "exShots", "flags"):
            values = g.get(key, [])
            if len(values) != len(set(values)):
                errors.append(f"{where}: {key} に重複があります")
            if key in g and not values:
                errors.append(f"{where}: {key} が空です")
        if "exShots" in g and not any(d in ("Ex", "Ph") for d in g.get("difficulties", [])):
            errors.append(f"{where}: exShots があるのに Extra がありません")
        hue = g.get("hue")
        if isinstance(hue, bool) or not isinstance(hue, int) or not 0 <= hue < 360:
            errors.append(f"{where}: hue は 0〜359 にしてください")
    for g in games:
        ref = g.get("remakeOf")
        if ref is not None and ref not in seen:
            errors.append(f"{g.get('id')}: remakeOf {ref!r} が見つかりません")
    return errors


VALIDATORS = {"games": validate_games}


def block(name: str, doc: dict) -> str:
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return (f"<!-- data:{name}:begin -->\n"
            f'<script type="application/json" id="data-{name}">{payload}</script>\n'
            f"<!-- data:{name}:end -->")


COMMENT = re.compile(r"/\*.*?\*/", re.S)
DECL = re.compile(r"(--[\w-]+)\s*:\s*([^;]+)")
VAR_USE = re.compile(r"var\((--[\w-]+)\)")  # 既定値のない var() だけ（既定値ありは未定義でも動く）
LIGHT = re.compile(r"^:root\s*\{(.*?)\}", re.S | re.M)
DARK = re.compile(r'@media \(prefers-color-scheme:dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{(.*?)\}\s*\}', re.S)
DARK_SELECTED = re.compile(r':root\[data-theme="dark"\]')
DESIGN_REGION = re.compile(r"<!-- design:begin -->.*?<!-- design:end -->", re.S)
STYLE = re.compile(r"<style[^>]*>(.*?)</style>", re.S | re.I)


def decls(body: str) -> dict[str, str]:
    return {k: " ".join(v.split()) for k, v in DECL.findall(body)}


def validate_design(tokens: str, components: str) -> list[str]:
    """tokens.css の形と、部品が使うトークンが定義済みかを調べる。"""
    errors: list[str] = []
    for name, text in (("tokens.css", tokens), ("components.css", components)):
        if "</style" in text.lower():
            errors.append(f"{name} に </style> を書かないでください（埋め込み先の <style> が途中で閉じます）")
    t = COMMENT.sub("", tokens)
    light, dark = LIGHT.search(t), DARK.search(t)
    if not (light and dark):
        return errors + ['tokens.css に :root と @media (prefers-color-scheme:dark){:root:not([data-theme="light"]){…}} の 2 ブロックが必要です']
    if DARK_SELECTED.search(t):
        errors.append(':root[data-theme="dark"] は sync_data.py が @media のブロックから作るので、tokens.css には書かないでください')
    lv, dv = decls(light.group(1)), decls(dark.group(1))
    extra = sorted(dv.keys() - lv.keys())
    if extra:
        errors.append(f"ダークだけで定義されたトークンがあります（:root にライトの値も書いてください）: {extra}")
    c = COMMENT.sub("", components)
    missing = sorted(set(VAR_USE.findall(c)) - lv.keys() - decls(c).keys())
    if missing:
        errors.append(f"components.css が未定義のトークンを使っています: {missing}")
    return errors


def validate_page_tokens(rel: str, html: str, tokens: str, components: str) -> list[str]:
    """ページ固有の <style> が、どこにも定義のないトークンを使っていないか調べる。

    --h や --p のようにインラインの style や JS で値を入れるものもあるので、
    「ページ内のどこかに `--名前:` があれば定義済み」とみなす。
    """
    page = DESIGN_REGION.sub("", html)
    defined = (decls(COMMENT.sub("", tokens)).keys() | decls(COMMENT.sub("", components)).keys()
               | decls(page).keys())
    used = {v for css in STYLE.findall(page) for v in VAR_USE.findall(COMMENT.sub("", css))}
    missing = sorted(used - defined)
    return [f"{rel} が未定義のトークンを使っています: {missing}"] if missing else []


def design_block(fonts: str, tokens: str, components: str) -> str:
    """埋め込む区間を作る。ダークの値は @media のブロックを :root[data-theme="dark"] にも複製する。"""
    dark = DARK.search(tokens)
    selected = f':root[data-theme="dark"]{{{dark.group(1)}}}' if dark else ""
    css = "\n\n".join(s.strip() for s in (tokens, selected, components) if s.strip())
    return f'<!-- design:begin -->\n{fonts.strip()}\n<style id="design">\n{css}\n</style>\n<!-- design:end -->'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="書き換えず、更新が必要かだけ調べる")
    args = ap.parse_args()

    # 1. 元データを読んで検証する（ここでは何も書き換えない）
    errors: list[str] = []
    writes: dict[Path, str] = {}  # 書き換えるファイル -> 新しい内容
    regions: list[tuple[str, str, re.Pattern, str]] = []  # (HTML, 区間名, パターン, 中身)
    for name, targets in TARGETS.items():
        src = DATA / f"{name}.json"
        text = src.read_text(encoding="utf-8")
        doc = json.loads(text)
        errors += [f"{src.relative_to(ROOT).as_posix()}: {e}" for e in VALIDATORS[name](doc)]
        formatted = dump(doc) + "\n"
        if formatted != text:
            writes[src] = formatted
        pattern = re.compile(rf"<!-- data:{name}:begin -->.*?<!-- data:{name}:end -->", re.S)
        regions += [(rel, f"data:{name}", pattern, block(name, doc)) for rel in targets]

    fonts, tokens, components = ((DESIGN / f).read_text(encoding="utf-8")
                                 for f in ("fonts.html", "tokens.css", "components.css"))
    errors += [f"design/: {e}" for e in validate_design(tokens, components)]
    design = design_block(fonts, tokens, components)
    regions += [(rel, "design", DESIGN_REGION, design) for rel in DESIGN_TARGETS]

    # 2. 埋め込み区間を置き換えた内容を作る
    pages: dict[str, str] = {}
    for rel, marker, pattern, new in regions:
        html = pages.get(rel) or (ROOT / rel).read_text(encoding="utf-8")
        if not pattern.search(html):
            errors.append(f"{rel} に {marker} の埋め込み区間がありません")
            continue
        pages[rel] = pattern.sub(lambda _: new, html, count=1)
    for rel in DESIGN_TARGETS:
        if rel in pages:
            errors += validate_page_tokens(rel, pages[rel], tokens, components)

    if errors:
        print("エラーがあります（どのファイルも書き換えていません）:", *errors, sep="\n  ", file=sys.stderr)
        return 2

    # 3. 変わったファイルだけ書き込む
    for rel, html in pages.items():
        if html != (ROOT / rel).read_text(encoding="utf-8"):
            writes[ROOT / rel] = html
    stale = [p.relative_to(ROOT).as_posix() for p in writes]
    if args.check:
        if stale:
            print("更新が必要です（uv run scripts/sync_data.py を実行してください）:", *stale, sep="\n  ")
            return 1
    else:
        for path, text in writes.items():
            path.write_text(text, encoding="utf-8", newline="\n")  # Windows でも改行は LF のまま
    print("更新しました:" if stale else "変更はありません", *stale, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

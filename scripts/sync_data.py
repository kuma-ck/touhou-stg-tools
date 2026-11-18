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
        if not 0 <= g.get("hue", -1) < 360:
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


def decls(body: str) -> dict[str, str]:
    return {k: " ".join(v.split()) for k, v in DECL.findall(body)}


def validate_design(tokens: str, components: str) -> list[str]:
    """ライトとダークで定義がそろっているか、部品が使うトークンが定義済みかを調べる。"""
    errors: list[str] = []
    t = COMMENT.sub("", tokens)
    light = re.search(r"^:root\s*\{(.*?)\}", t, re.S | re.M)
    dark_os = re.search(r'@media \(prefers-color-scheme:dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\s*\{(.*?)\}\s*\}', t, re.S)
    dark_sel = re.search(r':root\[data-theme="dark"\]\s*\{(.*?)\}', t, re.S)
    if not (light and dark_os and dark_sel):
        return ['tokens.css に :root・@media (prefers-color-scheme:dark)・:root[data-theme="dark"] の 3 ブロックが必要です']
    lv, dv, sv = decls(light.group(1)), decls(dark_os.group(1)), decls(dark_sel.group(1))
    if dv != sv:
        diff = sorted(k for k in dv.keys() | sv.keys() if dv.get(k) != sv.get(k))
        errors.append(f"ダークの 2 ブロックの値が一致しません: {diff}")
    extra = sorted((dv.keys() | sv.keys()) - lv.keys())
    if extra:
        errors.append(f"ダークだけで定義されたトークンがあります（:root にライトの値も書いてください）: {extra}")
    c = COMMENT.sub("", components)
    defined = lv.keys() | decls(c).keys()
    used = set(re.findall(r"var\((--[\w-]+)\)", c))  # 既定値のない var() だけを調べる
    missing = sorted(used - defined)
    if missing:
        errors.append(f"components.css が未定義のトークンを使っています: {missing}")
    return errors


def design_block() -> str:
    fonts = (DESIGN / "fonts.html").read_text(encoding="utf-8").strip()
    css = "\n\n".join((DESIGN / f).read_text(encoding="utf-8").strip() for f in DESIGN_CSS)
    return f'<!-- design:begin -->\n{fonts}\n<style id="design">\n{css}\n</style>\n<!-- design:end -->'


def embed(rel: str, marker: str, pattern: re.Pattern, new: str, stale: list[str], check: bool) -> bool:
    """rel の埋め込み区間を new に置き換える。区間がなければ False を返す。"""
    path = ROOT / rel
    html = path.read_text(encoding="utf-8")
    if not pattern.search(html):
        print(f"{rel} に {marker} の埋め込み区間がありません", file=sys.stderr)
        return False
    updated = pattern.sub(lambda _: new, html, count=1)
    if updated != html:
        stale.append(rel)
        if not check:
            path.write_text(updated, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="書き換えず、更新が必要かだけ調べる")
    args = ap.parse_args()

    stale: list[str] = []
    for name, targets in TARGETS.items():
        src = DATA / f"{name}.json"
        text = src.read_text(encoding="utf-8")
        doc = json.loads(text)
        errors = VALIDATORS[name](doc)
        if errors:
            print(f"{src.relative_to(ROOT)} にエラーがあります:", *errors, sep="\n  ", file=sys.stderr)
            return 2
        formatted = dump(doc) + "\n"
        if formatted != text:
            stale.append(str(src.relative_to(ROOT)))
            if not args.check:
                src.write_text(formatted, encoding="utf-8")

        pattern = re.compile(rf"<!-- data:{name}:begin -->.*?<!-- data:{name}:end -->", re.S)
        for rel in targets:
            if not embed(rel, f"data:{name}", pattern, block(name, doc), stale, args.check):
                return 2

    tokens = (DESIGN / "tokens.css").read_text(encoding="utf-8")
    components = (DESIGN / "components.css").read_text(encoding="utf-8")
    errors = validate_design(tokens, components)
    if errors:
        print("design/ にエラーがあります:", *errors, sep="\n  ", file=sys.stderr)
        return 2
    pattern = re.compile(r"<!-- design:begin -->.*?<!-- design:end -->", re.S)
    for rel in DESIGN_TARGETS:
        if not embed(rel, "design", pattern, design_block(), stale, args.check):
            return 2

    if args.check and stale:
        print("更新が必要です（uv run scripts/sync_data.py を実行してください）:", *stale, sep="\n  ")
        return 1
    print("更新しました:" if stale else "変更はありません", *stale, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())

# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ツールの HTML を Claude のアーティファクト公開用の形に変換して dist/ に書き出す。

アーティファクトは公開時に <!doctype>・<html>・<head>・<body> と charset / viewport
を自動で付けるため、それらを取り除いた本文だけを渡す必要がある。

使い方:
    uv run scripts/export_artifact.py clear-tracker   # -> dist/clear-tracker.html
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def to_artifact(html: str) -> str:
    head = re.search(r"<head>(.*?)</head>", html, re.S | re.I)
    body = re.search(r"<body[^>]*>(.*?)</body>", html, re.S | re.I)
    if not head or not body:
        raise ValueError("<head> と <body> が見つかりません")
    head_inner = re.sub(r'<meta\s+(charset|name="viewport")[^>]*>\s*', "", head.group(1), flags=re.I)
    return head_inner.strip() + "\n\n" + body.group(1).strip() + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    tool = sys.argv[1].strip("/")
    src = ROOT / tool / "index.html"
    out = ROOT / "dist" / f"{tool}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(to_artifact(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(out.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())

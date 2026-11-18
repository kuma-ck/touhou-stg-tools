# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# touhou-stg-tools

東方Project原作STG向けの非公式ファンツール集。GitHub Pages（main ブランチのルート）で公開する。

## コマンド
ビルド・リンターはない。Python のスクリプトは uv で実行する（`uv run`）。`scripts/` は Python 3.10 以上・標準ライブラリのみで、必要な Python のバージョンと依存は各ファイル先頭のインラインメタデータ（`# /// script`）に書く。

```sh
uv run scripts/sync_data.py          # data/*.json と design/ を検証し、HTML の埋め込みを更新
uv run scripts/sync_data.py --check  # 更新が必要なら終了コード 1（検証エラーは 2）
uv run scripts/export_artifact.py clear-tracker   # -> dist/clear-tracker.html（dist/ は gitignore）
uv run python -m unittest discover -s tests -v    # 単体テスト（scripts/ の関数）
uv run tests/e2e.py                  # E2E テスト（Playwright。ローカルにサーバーを立てて 3 ページを操作する）
```

E2E テストは Microsoft Edge を使う。Edge がない環境では先に `uv run --with playwright playwright install chromium` を実行する。

動作確認は `<tool>/index.html` をブラウザで直接開けばよい（localStorage モードで動く）。

## ルール
- 各ツールは `<tool>/index.html` の 1 ファイルで完結させる（外部の JS/CSS/データを読み込まない。Google Fonts のみ可）。
- 共通データは `data/*.json` が正。HTML 側の `<!-- data:NAME:begin/end -->` 区間は手で編集せず、`uv run scripts/sync_data.py` で更新する。コミット前に `uv run scripts/sync_data.py --check` が通ること。
- 見た目の共通部分（フォント、デザイントークン、共通部品の CSS）は `design/` が正。HTML 側の `<!-- design:begin/end -->` 区間も手で編集せず、`sync_data.py` で更新する。
- 色・文字サイズ・余白・角丸は `design/tokens.css` のトークン（`var(--accent)` など）で指定し、値を直接書かない。ライトとダークの両方の値を持つので、新しい色が要るときは tokens.css の `:root`（ライト）と `@media (prefers-color-scheme:dark)`（ダーク）の両方に足す。明示的にダークを選んだとき用の `:root[data-theme="dark"]` は sync_data.py が @media のブロックから作るので、tokens.css には書かない。
- ページ固有の CSS で使うトークンも、どこかで定義されている必要がある（sync_data.py が検査する）。CSS ファイルに `</style>` を書かない。
- `games.json` の `id` と `shots` の名前は記録データのキーなので、既存の値は変えない。
- ゲームから抜き出した画像・音声・ロゴは使わない。画面とREADMEに二次創作の表記を入れる。
- UI の文言は日本語。

## 構成
- `scripts/sync_data.py` の `TARGETS` が「データ名 → 埋め込み先 HTML」の対応表。共通データを使うツールを足したら、ここに登録し、HTML に埋め込み区間を置く。
- `sync_data.py` の `DESIGN_TARGETS` がデザインシステムの埋め込み先。新しいツールは `<head>` の自分の `<style>` より前に `<!-- design:begin -->` `<!-- design:end -->` を置いて登録する。ツール固有の CSS はその後ろの `<style>` に書く。
- `design/components.css` は全ツール共通の部品（`.card` `.btn` `.chip` `.pill` `.notice` `.field` `.seg` `.tog` `.ring` `.foot` など）。部品を足したり変えたら、見本ページ `design/index.html` も更新する。components.css で既定値なしの `var(--x)` を使うと、そのトークンが tokens.css か components.css に定義されていないと検証で落ちる。
- `dodge-sim/` と `route-planner/` は README だけの準備中ツール（まだ `index.html` はなく、`TARGETS` / `DESIGN_TARGETS` にも未登録）。
- `games.json` に項目を足すときは、`sync_data.py` の `GAME_KEYS`（必須なら `REQUIRED` も）を更新しないと検証で落ちる。難易度は `E N H L Ex Ph` のみ。
- ツールを公開したら、ルートの `index.html` のカードと README の表の状態（公開中／準備中）も更新する。
- `export_artifact.py` は `<head>` と `<body>` の中身だけを取り出し、charset と viewport の meta を除く（アーティファクト側が付けるため）。HTML はこの形に変換できる構造を保つ。

## 東方クリア表
- 保存先は 2 通り: Claude のアーティファクト内では `window.claude.use("db")`（コレクション `games`、1 作品 1 ドキュメント）、それ以外は localStorage（キー `touhou-stg-tools:clear-tracker:v1`）。どちらかは `window.claude.use` の有無と iframe 内かどうかで判定している（`IN_CLAUDE`）。ファイルの書き出し（バックアップ JSON・CSV）も同じ判定で分かれ、アーティファクト内では `window.claude.use("downloads")`、それ以外は Blob のリンクでダウンロードする。
- 記録の形式（cells / hidden / skip、バックアップ JSON の `app: "touhou-clear"`）は Google ドライブへの定期バックアップと復元機能が依存しているので、変えるときは互換を保つ。
- `cells` のキーは `"<機体名>|<難易度>"`。値は `c`（クリア）・`cc`（ノーコン）・`nb`・`nm`・`nmnb` の真偽値と、`x`（作品固有の `flags`）、`date`、`note`。段階は クリア < ノーコン < NB/NM < NMNB で、集計の「達成」はノーコン以上。Extra / Phantasm にはコンティニューがないので、クリアは `cc` として保存する。
- `exShots` がある作品では、Extra / Phantasm だけ `exShots` の機体を使う（`shotsFor`）。
- Claude のアーティファクトへ反映するときは `uv run scripts/export_artifact.py clear-tracker` の出力（`dist/clear-tracker.html`）を既存アーティファクトの URL に公開する。

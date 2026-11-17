# touhou-stg-tools

東方Project原作STG向けの非公式ファンツール集。GitHub Pages（main ブランチのルート）で公開する。

## ルール
- 各ツールは `<tool>/index.html` の 1 ファイルで完結させる（外部の JS/CSS/データを読み込まない。Google Fonts のみ可）。
- 共通データは `data/*.json` が正。HTML 側の `<!-- data:NAME:begin/end -->` 区間は手で編集せず、`python scripts/sync_data.py` で更新する。コミット前に `python scripts/sync_data.py --check` が通ること。
- `games.json` の `id` と `shots` の名前は記録データのキーなので、既存の値は変えない。
- ゲームから抜き出した画像・音声・ロゴは使わない。画面とREADMEに二次創作の表記を入れる。
- UI の文言は日本語。

## 東方クリア表
- 保存先は 2 通り: Claude のアーティファクト内では `window.claude.use("db")`（コレクション `games`、1 作品 1 ドキュメント）、それ以外は localStorage（キー `touhou-stg-tools:clear-tracker:v1`）。
- 記録の形式（cells / hidden / skip、バックアップ JSON の `app: "touhou-clear"`）は Google ドライブへの定期バックアップと復元機能が依存しているので、変えるときは互換を保つ。
- Claude のアーティファクトへ反映するときは `python scripts/export_artifact.py clear-tracker` の出力（`dist/clear-tracker.html`）を既存アーティファクトの URL に公開する。

# touhou-stg-tools

東方Project原作STG（整数作品）のやり込みを支える、非公式のファンツール集です。

> 東方Projectの二次創作です。上海アリス幻樂団とは関係ありません。
> ゲームから抜き出した画像・音声などの素材は含みません。

公開ページ: https://kuma-ck.github.io/touhou-stg-tools/

## ツール

| ツール | 状態 | 内容 |
| --- | --- | --- |
| [東方クリア表](clear-tracker/) | 公開中 | 機体×難易度ごとのクリア・ノーコン・NB・NM・NMNB を記録。達成日・メモ、バックアップ/復元、CSV 書き出し |
| [ちょん避けシミュレーター](dodge-sim/) | 準備中 | 自機狙い弾のちょん避けを練習する |
| [ボムルート構築](route-planner/) | 準備中 | ステージのどこでボムを使うかを計画する |

### 東方クリア表の保存先

- GitHub Pages で開いた場合: 記録はそのブラウザの localStorage に保存されます。端末間では同期しないので、移すときは「バックアップを保存」→ 別の端末で「バックアップから復元」を使ってください。
- Claude のアーティファクトとして開いた場合: Claude 側のデータベースに保存され、同じアカウントの端末間で同期します。

## 構成

```
touhou-stg-tools/
├─ index.html         # GitHub Pages のトップ（ツール一覧）
├─ data/              # ツール間で共有するデータ
│  └─ games.json      #   作品・機体・難易度
├─ design/            # デザインシステム（全ツール共通の見た目）
│  ├─ tokens.css      #   デザイントークン（色・文字サイズ・余白・角丸。ライト/ダーク）
│  ├─ components.css  #   共通部品（カード、ボタン、チップ、入力欄、進捗リングなど）
│  ├─ fonts.html      #   Google Fonts の読み込み
│  └─ index.html      #   見本ページ
├─ clear-tracker/     # 東方クリア表（1 ファイルで完結する HTML）
├─ dodge-sim/         # ちょん避けシミュレーター（準備中）
├─ route-planner/     # ボムルート構築（準備中）
└─ scripts/           # Python のメンテナンス用スクリプト（標準ライブラリのみ）
```

各ツールは外部ファイルを読み込まない 1 ファイルの HTML にしています。GitHub Pages でも、ローカルでファイルを直接開いても、Claude のアーティファクトとしても同じものが動きます。そのため `data/` のデータと `design/` の CSS は HTML に埋め込んでおり、元を直したら下のスクリプトで埋め込みを更新します。

### デザインシステム

色・文字・余白などの決まり（デザイントークン）と、ボタンやカードなどの共通部品を `design/` にまとめています。どのツールも同じ値を使うので、たとえば `design/tokens.css` のアクセント色を 1 か所直してスクリプトを実行すれば、全ツールの色が変わります。一覧は[見本ページ](design/)で見られます。

- 色や大きさは `var(--accent)` `var(--sp-4)` のようにトークンで指定し、値を直接書かない
- 各ツールの HTML の `<!-- design:begin -->` 〜 `<!-- design:end -->` は自動で書き換わるので、手で編集しない
- ツール固有の見た目は、その後ろの `<style>` に書く

## 開発

ビルドは不要です。メンテナンス用スクリプトは [uv](https://docs.astral.sh/uv/) で実行します。必要な Python（3.10 以上）は uv が用意するので、別に入れる必要はありません。

```sh
# data/*.json と design/ を検証し、各ツールの HTML の埋め込みを更新
uv run scripts/sync_data.py

# 埋め込みが最新か確認だけする（CI 用。更新が必要なら終了コード 1）
uv run scripts/sync_data.py --check

# Claude のアーティファクト公開用に変換（dist/ に出力）
uv run scripts/export_artifact.py clear-tracker
```

### 作品データを直す・新作を足す

`data/games.json` の `games` に 1 件追加して `uv run scripts/sync_data.py` を実行します。

| 項目 | 必須 | 内容 |
| --- | --- | --- |
| `id` | ○ | 一意な ID（`th21` など）。記録データのキーになるので、一度決めたら変えない |
| `no` | ○ | 表示用の番号 |
| `title` / `titleEn` | ○ / − | 作品名 |
| `year` | ○ | 発売年 |
| `hue` | ○ | テーマ色の色相（0〜359） |
| `difficulties` | ○ | `E` `N` `H` `L` `Ex` `Ph` から |
| `shots` | ○ | 機体の一覧。記録のキーになるので、名前を変えると既存の記録と結びつかなくなる |
| `exShots` | − | Extra だけ機体構成が違う作品（天空璋など） |
| `flags` | − | 作品固有の印（永夜抄の Final A/B など） |
| `remakeOf` | − | リメイク元の `id` |

機体構成などに誤りがあれば Issue で教えてください。

## ライセンス

コードは [MIT License](LICENSE) です。東方Projectに関する権利は原作者に帰属します。

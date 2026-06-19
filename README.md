# Pegasus-AI MCP サーバ

本体リポジトリ [`Pegasus-ai`](https://github.com/michirum10/Pegasus-ai) の
**スクレイピング・データ取得・予測・期待値計算**の主要関数を、
Python 公式 MCP SDK（`mcp.server.fastmcp.FastMCP`、stdio トランスポート）経由で
Claude Desktop などの MCP クライアントから呼び出せるようにするサーバです。

> 本体ロジックは再実装していません。`Pegasus-ai` 側の関数を **そのまま呼び出す**
> 薄い接続層（sys.path 追加 / CSV 読み込み / DataFrame→JSON 変換 / エラー処理）のみを実装しています。

---

## 1. 本体関数の棚卸しと公開対象の選定

`Pegasus-ai` 内のスクレイピング・データ取得・予測に関する主要関数を洗い出し、
MCP ツールとして公開するのに適したものを選定しました。

### 洗い出した主要関数

| 区分 | ファイル | 関数 | 主な引数 | 概要 |
|------|----------|------|----------|------|
| スクレイピング | `scraper/collect_race_data.py` | `get_kaisai_dates` | `session, year, month` | カレンダーから開催日(YYYYMMDD)一覧を取得 |
| スクレイピング | `scraper/collect_race_data.py` | `get_race_ids` | `session, date` | 開催日ページから JRA の race_id(12桁) 一覧を取得 |
| スクレイピング | `scraper/collect_race_data.py` | `get_race_result` | `session, race_id, race_date` | レース結果テーブル＋距離/馬場等メタを DataFrame で取得 |
| スクレイピング | `scraper/collect_race_data.py` | `make_session` | （なし） | リクエスト用 Session を生成（内部利用） |
| スクレイピング | `src/data_processor.py` | `scrape_live_data` | `race_id, base_url` | 出馬表ページから当日の出走馬を取得 |
| データ取得/変換 | `scraper/convert_to_model_format.py` | `convert` | `input_path, output_path` | 日本語カラムの生 CSV を学習用フォーマットへ変換 |
| データ前処理 | `src/data_processor.py` | `load_historical_data` | `csv_path` | 履歴 CSV を読み込み |
| データ前処理 | `src/data_processor.py` | `clean_data` | `df` | 欠損補完・型整形・馬場状態の数値化 |
| データ前処理 | `src/data_processor.py` | `process_race_data` | `input_path, output_path` | 読み込み→クレンジング→保存を一括実行 |
| 予測 | `src/predict_engine.py` | `train_model` | `train_csv_path, model_path` | LightGBM モデルを学習し pkl 保存 |
| 予測 | `src/predict_engine.py` | `predict_probability` | `test_df, model_path` | 学習済みモデルで各馬の勝率を予測 |
| 期待値 | `src/value_calculator.py` | `run_value_pipeline` | `predicted_csv, output_json, include_dark_horse` | 確信度ギャップで S/A/D ランクの買い目を抽出 |
| 期待値 | `src/value_calculator.py` | `score_and_rank` / `calculate_expected_value` / `find_dark_horse_picks` | `df` | ランク付け・EV 計算・大穴抽出（`run_value_pipeline` の内部部品） |

### MCP ツールとして公開した関数と選定理由

| MCP ツール名 | 元関数 | 選定理由 |
|--------------|--------|----------|
| `get_kaisai_dates` | `get_kaisai_dates` | 入出力が単純な値（年月→日付配列）で、データ取得の起点。冪等な読み取り操作。 |
| `get_race_ids` | `get_race_ids` | 開催日→race_id 配列という明快な入出力。スクレイピングの中核。 |
| `get_race_result` | `get_race_result` | レース結果という最も価値の高いデータを取得。JSON 化しやすい表形式。 |
| `scrape_live_data` | `scrape_live_data` | 当日出馬表（予測の入力）を取得。race_id 1 つで完結し対話的に使いやすい。 |
| `process_race_data` | `process_race_data` | スクレイピング結果を予測可能な形へ整える前処理の代表。 |
| `train_model` | `train_model` | 予測の要となる学習処理を再現可能な形で公開。 |
| `predict_win_rate` | `predict_probability` | 学習済みモデルでの推論。本サービスの主目的（勝率予測）そのもの。 |
| `run_value_pipeline` | `run_value_pipeline` | 予測結果を実用的な買い目（S/A/D ランク）に落とし込む集大成。 |

**選定方針**: 引数が JSON で表現でき、戻り値を構造化データとして返せる「自己完結した
ユースケースの単位」を優先しました。`make_session` や `clean_data` などは他関数の
内部部品のため単体公開せず、`get_*` / `process_race_data` の内部で利用しています。

---

## 2. 公開ツール一覧

| ツール | 引数 | 戻り値（主なキー） |
|--------|------|--------------------|
| `get_kaisai_dates` | `year:int, month:int` | `ok, year, month, count, dates[]` |
| `get_race_ids` | `date:str(YYYYMMDD)` | `ok, date, count, race_ids[]` |
| `get_race_result` | `race_id:str, race_date:str=""` | `ok, found, race_id, row_count, records[]` |
| `scrape_live_data` | `race_id:str` | `ok, race_id, row_count, records[]` |
| `process_race_data` | `input_path:str="", output_path:str=""` | `ok, rows, columns, column_names[], output_path` |
| `train_model` | `train_csv_path:str="", model_path:str=""` | `ok, model_path, feature_count, feature_columns[]` |
| `predict_win_rate` | `input_csv:str, model_path:str="", limit:int=50` | `ok, row_count, returned, records[]` |
| `run_value_pipeline` | `predicted_csv:str="", output_json:str="", include_dark_horse:bool=True` | `ok, total, rank_counts{}, records[]` |

- すべてのツールはエラー時に `{"ok": false, "error_type": ..., "error": ...}` を返します。
- `train_model` / `predict_win_rate` は `lightgbm` / `scikit-learn` を必要とします
  （未インストール時はエラーレスポンスを返します）。

---

## 3. セットアップ

```bash
# 依存をインストール（予測系を使う場合は lightgbm / scikit-learn も）
pip install -r requirements.txt
# pip install lightgbm scikit-learn   # train_model / predict_win_rate を使う場合

# テスト
pytest -v

# 手動起動（stdio）
PEGASUS_AI_ROOT=/path/to/Pegasus-ai python mcp_server.py
```

`PEGASUS_AI_ROOT` には本体リポジトリ `Pegasus-ai` のパスを指定します。
未指定の場合は本リポジトリの兄弟ディレクトリ `../Pegasus-ai` を既定とします。

---

## 4. Claude Desktop での設定

Claude Desktop の設定ファイル `claude_desktop_config.json` に以下を追記します。

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "pegasus-ai": {
      "command": "python",
      "args": [
        "/absolute/path/to/pegasus-mcp/mcp_server.py"
      ],
      "env": {
        "PEGASUS_AI_ROOT": "/absolute/path/to/Pegasus-ai"
      }
    }
  }
}
```

### 補足

- `command` は Python 実行ファイルです。仮想環境を使う場合はその中の
  `python`（例: `/path/to/venv/bin/python`、Windows なら
  `C:\\path\\to\\venv\\Scripts\\python.exe`）を絶対パスで指定してください。
- `args` には `mcp_server.py` の **絶対パス**を指定します。
- `env.PEGASUS_AI_ROOT` に本体リポジトリ `Pegasus-ai` の絶対パスを指定します。
- 設定を保存したら Claude Desktop を再起動すると、チャット内で
  `pegasus-ai` のツール（`get_race_result` など）が利用可能になります。

`uv` を使う場合の例:

```json
{
  "mcpServers": {
    "pegasus-ai": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/pegasus-mcp",
        "run",
        "mcp_server.py"
      ],
      "env": {
        "PEGASUS_AI_ROOT": "/absolute/path/to/Pegasus-ai"
      }
    }
  }
}
```

---

## 5. Threads 自動投稿

毎週土日のレース終了後（JST 17:30）に、その日のレース結果を自動分析し
Threads に投稿する機能です。GitHub Actions で動くため **PC の常時起動は不要** です。

### 投稿イメージ

```
【中央競馬 AI データ分析】6/21(土)

全12R 分析完了
波乱度: ★★★☆☆
最高配当: テスト馬A（単勝 25.0倍）
万馬券級（10倍超）: 2R

注目の高配当:
  テスト馬A 25.0倍
  テスト馬B 12.5倍

#競馬 #中央競馬 #AI分析 #データ競馬
by Pegasus-AI
```

### セットアップ手順

#### 1. Threads API のアクセストークンを取得

1. [Meta for Developers](https://developers.facebook.com/) でアプリを作成
2. 「ユースケース」→「Threads API にアクセス」を選択
3. 必要な権限: `threads_basic`, `threads_content_publish`
4. アクセストークンを生成し、長期トークンに交換する
5. **ユーザ ID** と **長期アクセストークン** を控える

> 長期トークンの有効期限は 60 日間です。期限前に再取得する必要があります。

#### 2. GitHub Secrets を設定

リポジトリの Settings → Secrets and variables → Actions で以下を追加:

| Secret 名 | 値 |
|---|---|
| `THREADS_USER_ID` | Threads ユーザ ID |
| `THREADS_ACCESS_TOKEN` | Threads 長期アクセストークン |
| `PEGASUS_AI_TOKEN` | Pegasus-ai リポジトリを読める GitHub Personal Access Token（private リポジトリのため必要） |

#### 3. 動作確認（手動実行）

GitHub → Actions → 「Threads 自動投稿（週末レース結果）」→ Run workflow で手動実行できます。

- `dry_run` にチェックを入れると、投稿せずにテキストだけ出力します（初回テスト推奨）

#### ローカルでのテスト

```bash
# dry-run（投稿しない）で過去の開催日を指定して動作確認
PEGASUS_AI_ROOT=/path/to/Pegasus-ai python threads_poster.py --date 20250607 --dry-run
```

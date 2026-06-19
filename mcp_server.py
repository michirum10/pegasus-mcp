"""Pegasus-AI MCP サーバ.

本体リポジトリ ``Pegasus-ai`` のスクレイピング・データ取得・予測・期待値計算の
主要関数を、Python 公式 MCP SDK（``mcp.server.fastmcp.FastMCP``）を用いて
stdio トランスポートの MCP ツールとして公開する。

設計方針:
    * 既存ロジックは再実装せず、``Pegasus-ai`` 側の関数をそのまま呼び出す。
      本ファイルが担うのは「sys.path への追加」「CSV の読み込み」「DataFrame →
      JSON 互換レコードへの変換」「エラーハンドリング」といった薄い接続層のみ。
    * lightgbm / scikit-learn など重量級の依存はツール実行時に遅延 import する。
      これによりスクレイピング系ツールしか使わない場合でもサーバが起動できる。

環境変数:
    PEGASUS_AI_ROOT
        本体リポジトリ ``Pegasus-ai`` のルートパス。未指定時は本リポジトリの
        兄弟ディレクトリ ``../Pegasus-ai`` を既定とする。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# MCP サーバ本体。name はクライアント（Claude Desktop 等）に表示される。
mcp = FastMCP("pegasus-ai")


# --------------------------------------------------------------------------- #
# 本体リポジトリ（Pegasus-ai）への接続ユーティリティ
# --------------------------------------------------------------------------- #
def _pegasus_root() -> Path:
    """本体リポジトリ ``Pegasus-ai`` のルートパスを返す。

    環境変数 ``PEGASUS_AI_ROOT`` が設定されていればそれを優先し、
    未設定なら本ファイルの 1 つ上の階層にある ``Pegasus-ai`` を既定とする。

    Returns:
        Path: 本体リポジトリのルートディレクトリ。
    """
    env = os.environ.get("PEGASUS_AI_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # pegasus-mcp と Pegasus-ai が兄弟ディレクトリにある前提の既定値。
    return (Path(__file__).resolve().parent.parent / "Pegasus-ai").resolve()


def _ensure_pegasus_on_path() -> Path:
    """``Pegasus-ai`` のソースを import 可能にするため sys.path を整える。

    ルート・``src``・``scraper`` の各ディレクトリを sys.path 先頭に追加する
    （冪等。既に存在する場合は何もしない）。

    Returns:
        Path: 本体リポジトリのルートディレクトリ。

    Raises:
        FileNotFoundError: 本体リポジトリが見つからない場合。
    """
    root = _pegasus_root()
    if not root.exists():
        raise FileNotFoundError(
            f"Pegasus-ai リポジトリが見つかりません: {root} "
            f"(環境変数 PEGASUS_AI_ROOT で明示指定できます)"
        )
    for sub in (root, root / "src", root / "scraper"):
        p = str(sub)
        if sub.exists() and p not in sys.path:
            sys.path.insert(0, p)
    return root


def _df_to_records(df: Any, limit: int | None = None) -> list[dict[str, Any]]:
    """pandas.DataFrame を JSON 互換の辞書リストへ変換する。

    NaN は null に、numpy 型は素の Python 型に変換される。``limit`` を指定すると
    先頭 ``limit`` 行のみを返す（巨大なレスポンスを避けるため）。

    Args:
        df: 変換対象の DataFrame。
        limit: 返却する最大行数。None なら全行。

    Returns:
        list[dict]: 各行を辞書化したレコードのリスト。
    """
    if limit is not None:
        df = df.head(limit)
    # to_json 経由で NaN→null・numpy 型→Python 型の変換をまとめて行う。
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _error(exc: Exception) -> dict[str, Any]:
    """例外を統一フォーマットのエラーレスポンスに変換する。

    Args:
        exc: 捕捉した例外。

    Returns:
        dict: ``ok=False`` と例外の型・メッセージを含む辞書。
    """
    return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}


# --------------------------------------------------------------------------- #
# スクレイピング / データ取得系ツール
# --------------------------------------------------------------------------- #
@mcp.tool()
def get_kaisai_dates(year: int, month: int) -> dict[str, Any]:
    """指定した年月の JRA 開催日一覧を netkeiba から取得する。

    本体の ``scraper/collect_race_data.py`` の ``get_kaisai_dates`` を呼び出す。

    Args:
        year: 取得対象の西暦年（例: 2025）。
        month: 取得対象の月（1〜12）。

    Returns:
        dict: ``ok``・``year``・``month``・``count``・``dates``（YYYYMMDD の配列）。
    """
    try:
        _ensure_pegasus_on_path()
        import collect_race_data as crd  # 遅延 import

        session = crd.make_session()
        dates = crd.get_kaisai_dates(session, int(year), int(month))
        return {"ok": True, "year": year, "month": month, "count": len(dates), "dates": dates}
    except Exception as exc:  # noqa: BLE001 - MCP ツールでは握り潰してエラー返却
        return _error(exc)


@mcp.tool()
def get_race_ids(date: str) -> dict[str, Any]:
    """指定した開催日（YYYYMMDD）の JRA レース ID 一覧を取得する。

    本体の ``scraper/collect_race_data.py`` の ``get_race_ids`` を呼び出す。

    Args:
        date: 開催日。``YYYYMMDD`` 形式の 8 桁文字列（例: "20250105"）。

    Returns:
        dict: ``ok``・``date``・``count``・``race_ids``（12 桁 race_id の配列）。
    """
    try:
        _ensure_pegasus_on_path()
        import collect_race_data as crd  # 遅延 import

        session = crd.make_session()
        race_ids = crd.get_race_ids(session, str(date))
        return {"ok": True, "date": date, "count": len(race_ids), "race_ids": race_ids}
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool()
def get_race_result(race_id: str, race_date: str = "") -> dict[str, Any]:
    """指定した race_id のレース結果テーブルを取得する。

    本体の ``scraper/collect_race_data.py`` の ``get_race_result`` を呼び出す。
    着順・馬名・騎手・単勝オッズなどの結果に加え、距離・馬場状態などの
    メタ情報を各行へ付与した状態で返す。

    Args:
        race_id: 12 桁のレース ID（例: "202505010101"）。
        race_date: 開催日（YYYYMMDD）。分かっていれば精度向上のため渡す。

    Returns:
        dict: ``ok``・``race_id``・``row_count``・``records``（結果行の配列）。
              結果テーブルが存在しない場合は ``found=False``。
    """
    try:
        _ensure_pegasus_on_path()
        import collect_race_data as crd  # 遅延 import

        session = crd.make_session()
        df = crd.get_race_result(session, str(race_id), race_date=str(race_date))
        if df is None:
            return {"ok": True, "found": False, "race_id": race_id, "row_count": 0, "records": []}
        return {
            "ok": True,
            "found": True,
            "race_id": race_id,
            "row_count": int(len(df)),
            "records": _df_to_records(df),
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool()
def scrape_live_data(race_id: str) -> dict[str, Any]:
    """出馬表ページから当日の出走馬（ライブデータ）を取得する。

    本体の ``src/data_processor.py`` の ``scrape_live_data`` を呼び出す。

    Args:
        race_id: 出馬表を取得するレース ID。

    Returns:
        dict: ``ok``・``race_id``・``row_count``・``records``（出走馬の配列）。
    """
    try:
        _ensure_pegasus_on_path()
        import data_processor  # 遅延 import

        df = data_processor.scrape_live_data(str(race_id))
        return {
            "ok": True,
            "race_id": race_id,
            "row_count": int(len(df)),
            "records": _df_to_records(df),
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


# --------------------------------------------------------------------------- #
# データ前処理系ツール
# --------------------------------------------------------------------------- #
@mcp.tool()
def process_race_data(input_path: str = "", output_path: str = "") -> dict[str, Any]:
    """生の race CSV を学習用フォーマットへクレンジングして保存する。

    本体の ``src/data_processor.py`` の ``process_race_data`` を呼び出す。
    欠損値補完・馬場状態の数値化・型整形などを行い、NaN を含まない
    モデル学習用 CSV を出力する。

    Args:
        input_path: 入力 CSV パス。空文字なら本体既定（mock_races.csv）。
        output_path: 出力 CSV パス。空文字なら本体既定（processed_races.csv）。

    Returns:
        dict: ``ok``・``rows``・``columns``・``column_names``・``output_path``。
    """
    try:
        _ensure_pegasus_on_path()
        import data_processor  # 遅延 import

        # 空文字なら本体側の既定パスをそのまま使う。
        kwargs: dict[str, Any] = {}
        if input_path:
            kwargs["input_path"] = input_path
        if output_path:
            kwargs["output_path"] = output_path

        cleaned = data_processor.process_race_data(**kwargs)
        out = output_path or str(data_processor.DEFAULT_OUTPUT)
        return {
            "ok": True,
            "rows": int(len(cleaned)),
            "columns": int(len(cleaned.columns)),
            "column_names": list(cleaned.columns),
            "output_path": out,
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


# --------------------------------------------------------------------------- #
# 予測系ツール
# --------------------------------------------------------------------------- #
@mcp.tool()
def train_model(train_csv_path: str = "", model_path: str = "") -> dict[str, Any]:
    """学習用 CSV から LightGBM モデルを学習し pkl として保存する。

    本体の ``src/predict_engine.py`` の ``train_model`` を呼び出す。
    lightgbm / scikit-learn を必要とするため、未インストール時は
    エラーレスポンスを返す。

    Args:
        train_csv_path: 学習用 CSV パス。空文字なら本体既定。
        model_path: モデル出力先 pkl パス。空文字なら本体既定。

    Returns:
        dict: ``ok``・``model_path``・``feature_count``・``feature_columns``。
    """
    try:
        _ensure_pegasus_on_path()
        import predict_engine  # 遅延 import（lightgbm 依存）

        kwargs: dict[str, Any] = {}
        if train_csv_path:
            kwargs["train_csv_path"] = train_csv_path
        if model_path:
            kwargs["model_path"] = model_path

        artifact = predict_engine.train_model(**kwargs)
        out = model_path or str(predict_engine.MODEL_PATH)
        feature_columns = artifact.get("feature_columns", [])
        return {
            "ok": True,
            "model_path": out,
            "feature_count": len(feature_columns),
            "feature_columns": feature_columns,
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool()
def predict_win_rate(
    input_csv: str,
    model_path: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """学習済みモデルで各馬の勝率（predicted_win_rate）を予測する。

    本体の ``src/predict_engine.py`` の ``predict_probability`` を呼び出す。
    入力 CSV を読み込んで DataFrame として渡し、予測結果のレコードを返す。
    lightgbm を必要とするため、未インストール時はエラーレスポンスを返す。

    Args:
        input_csv: 予測対象の特徴量を含む CSV パス（必須）。
        model_path: 学習済み pkl パス。空文字なら本体既定。
        limit: 返却する最大行数（既定 50）。0 以下なら全行。

    Returns:
        dict: ``ok``・``row_count``（全行数）・``returned``（返却行数）・``records``。
    """
    try:
        _ensure_pegasus_on_path()
        import pandas as pd  # 遅延 import
        import predict_engine  # 遅延 import（lightgbm 依存）

        path = Path(input_csv).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"入力 CSV が見つかりません: {path}")

        test_df = pd.read_csv(path, encoding="utf-8-sig")
        kwargs: dict[str, Any] = {}
        if model_path:
            kwargs["model_path"] = model_path

        predicted = predict_engine.predict_probability(test_df, **kwargs)
        cap = None if (limit is None or limit <= 0) else int(limit)
        return {
            "ok": True,
            "row_count": int(len(predicted)),
            "returned": min(cap, len(predicted)) if cap else int(len(predicted)),
            "records": _df_to_records(predicted, limit=cap),
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


@mcp.tool()
def run_value_pipeline(
    predicted_csv: str = "",
    output_json: str = "",
    include_dark_horse: bool = True,
) -> dict[str, Any]:
    """予測済み CSV から期待値ランク（S/A/D）の買い目候補を抽出する。

    本体の ``src/value_calculator.py`` の ``run_value_pipeline`` を呼び出す。
    確信度ギャップによる S/A ランク格付けと、大穴候補（D ランク）抽出を行い、
    結果を JSON へ書き出すとともにレコードとして返す。

    Args:
        predicted_csv: 予測済み CSV パス。空文字なら本体既定（predicted_races.csv）。
        output_json: 出力 JSON パス。空文字なら本体既定（ev_results.json）。
        include_dark_horse: True なら大穴（D ランク）候補も含める。

    Returns:
        dict: ``ok``・``total``・``rank_counts``（ランク別件数）・``records``。
    """
    try:
        _ensure_pegasus_on_path()
        import value_calculator  # 遅延 import（pandas のみ）

        kwargs: dict[str, Any] = {"include_dark_horse": bool(include_dark_horse)}
        if predicted_csv:
            kwargs["predicted_csv"] = predicted_csv
        if output_json:
            kwargs["output_json"] = output_json

        picks = value_calculator.run_value_pipeline(**kwargs)
        rank_counts = {
            str(rank): int(count)
            for rank, count in picks["rank"].value_counts().items()
        } if "rank" in picks.columns else {}
        return {
            "ok": True,
            "total": int(len(picks)),
            "rank_counts": rank_counts,
            "records": _df_to_records(picks),
        }
    except Exception as exc:  # noqa: BLE001
        return _error(exc)


def main() -> None:
    """stdio トランスポートで MCP サーバを起動する（Claude Desktop 用エントリ）。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

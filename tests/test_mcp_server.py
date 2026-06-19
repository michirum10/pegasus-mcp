"""Pegasus-AI MCP サーバの最小テスト.

ネットワークや lightgbm を必要としない範囲で、各ツールが本体関数を正しく
呼び出していること・エラーハンドリングが機能していることを検証する。
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pandas as pd

import mcp_server


# --------------------------------------------------------------------------- #
# ツール登録 / ヘルパー
# --------------------------------------------------------------------------- #
def test_all_tools_registered() -> None:
    """想定した 8 ツールがすべて MCP に登録されていること。"""
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "get_kaisai_dates",
        "get_race_ids",
        "get_race_result",
        "scrape_live_data",
        "process_race_data",
        "train_model",
        "predict_win_rate",
        "run_value_pipeline",
    }
    assert expected <= names


def test_df_to_records_handles_nan() -> None:
    """NaN が null（None）へ変換され、limit が効くこと。"""
    df = pd.DataFrame({"a": [1, 2, 3], "b": [float("nan"), 5.0, 6.0]})
    records = mcp_server._df_to_records(df, limit=2)
    assert len(records) == 2
    assert records[0]["b"] is None


# --------------------------------------------------------------------------- #
# データ前処理ツール（本体 data_processor.process_race_data を実呼び出し）
# --------------------------------------------------------------------------- #
def test_process_race_data_cleans_csv(tmp_path: Path) -> None:
    """生 CSV をクレンジングし NaN なしの学習用 CSV を出力できること。"""
    src = tmp_path / "raw.csv"
    src.write_text(
        textwrap.dedent(
            """\
            race_id,horse_id,track_condition,distance,jockey_win_rate,predicted_win_rate,live_odds,ev_score
            R1,H1,良,1600,0.12,0.0,3.5,0.0
            R1,H2,稍重,1600,,0.0,8.1,0.0
            """
        ),
        encoding="utf-8",
    )
    out = tmp_path / "processed.csv"

    result = mcp_server.process_race_data(input_path=str(src), output_path=str(out))

    assert result["ok"] is True
    assert result["rows"] == 2
    assert out.exists()
    # 馬場状態（良/稍重）が 1/2 に数値化されていること。
    cleaned = pd.read_csv(out)
    assert set(cleaned["track_condition"]) <= {1, 2, 3, 4}


def test_process_race_data_missing_file_returns_error() -> None:
    """存在しない入力パスはエラーレスポンス（ok=False）になること。"""
    result = mcp_server.process_race_data(input_path="/no/such/file.csv")
    assert result["ok"] is False
    assert "error" in result


# --------------------------------------------------------------------------- #
# 期待値パイプラインツール（本体 value_calculator.run_value_pipeline を実呼び出し）
# --------------------------------------------------------------------------- #
def test_run_value_pipeline_ranks_picks(tmp_path: Path) -> None:
    """予測済み CSV から S/A ランクの買い目候補を抽出できること。"""
    predicted = tmp_path / "predicted.csv"
    predicted.write_text(
        textwrap.dedent(
            """\
            race_id,horse_id,horse_name,predicted_win_rate,live_odds
            R1,H1,アルファ,0.50,2.0
            R1,H2,ベータ,0.20,5.0
            R1,H3,ガンマ,0.10,12.0
            """
        ),
        encoding="utf-8",
    )
    out_json = tmp_path / "ev.json"

    result = mcp_server.run_value_pipeline(
        predicted_csv=str(predicted),
        output_json=str(out_json),
        include_dark_horse=False,
    )

    assert result["ok"] is True
    assert result["total"] >= 1
    # 確信度ギャップ 0.30 のためトップ馬は S ランクになる。
    assert result["rank_counts"].get("S", 0) == 1
    assert out_json.exists()


# --------------------------------------------------------------------------- #
# スクレイピングツール（ネットワークはモックして本体パーサを実呼び出し）
# --------------------------------------------------------------------------- #
def test_scrape_live_data_parses_horses(monkeypatch) -> None:
    """出馬表 HTML をパースして出走馬レコードを返せること。"""
    mcp_server._ensure_pegasus_on_path()
    import data_processor

    class _FakeResponse:
        status_code = 200
        text = (
            "<table><tr><td><a class='HorseName'>テスト馬A</a></td></tr>"
            "<tr><td><a class='HorseName'>テスト馬B</a></td></tr></table>"
        )

        def raise_for_status(self) -> None:  # noqa: D401 - スタブ
            return None

    # ネットワーク呼び出しと待機をスタブ化。
    monkeypatch.setattr(data_processor.requests, "get", lambda *a, **k: _FakeResponse())
    monkeypatch.setattr(data_processor.time, "sleep", lambda *a, **k: None)

    result = mcp_server.scrape_live_data("202505010101")

    assert result["ok"] is True
    assert result["row_count"] == 2
    names = {r["horse_name"] for r in result["records"]}
    assert {"テスト馬A", "テスト馬B"} <= names

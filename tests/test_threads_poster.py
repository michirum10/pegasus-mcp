"""threads_poster のユニットテスト。"""

from __future__ import annotations

import pytest

# テスト対象を直接 import（Pegasus-ai 不要な関数のみテスト）
from threads_poster import (
    analyze_results,
    format_post,
    ThreadsClient,
    MAX_POST_LENGTH,
)


# --------------------------------------------------------------------------- #
# analyze_results のテスト
# --------------------------------------------------------------------------- #
class TestAnalyzeResults:
    def test_empty_results(self):
        analysis = analyze_results([])
        assert analysis["has_data"] is False
        assert analysis["total_races"] == 0

    def test_normal_results(self):
        results = [
            {
                "race_id": "202505021201",
                "records": [
                    {"着順": "1", "馬名": "テスト馬A", "単勝": "3.5"},
                    {"着順": "2", "馬名": "テスト馬B", "単勝": "5.0"},
                ],
                "row_count": 2,
            },
        ]
        analysis = analyze_results(results)
        assert analysis["has_data"] is True
        assert analysis["total_races"] == 1
        assert analysis["upset_count"] == 0
        assert analysis["chaos_level"] == 1

    def test_upset_detection(self):
        results = [
            {
                "race_id": "202505021201",
                "records": [
                    {"着順": "1", "馬名": "大穴馬", "単勝": "45.2"},
                    {"着順": "2", "馬名": "テスト馬B", "単勝": "2.0"},
                ],
                "row_count": 2,
            },
        ]
        analysis = analyze_results(results)
        assert analysis["upset_count"] == 1
        assert analysis["top_odds"] == pytest.approx(45.2)
        assert analysis["top_horse"] == "大穴馬"

    def test_high_chaos_level(self):
        """全レースが波乱なら chaos_level=5。"""
        results = [
            {
                "race_id": f"20250502120{i}",
                "records": [
                    {"着順": "1", "馬名": f"穴馬{i}", "単勝": "15.0"},
                ],
                "row_count": 1,
            }
            for i in range(4)
        ]
        analysis = analyze_results(results)
        assert analysis["chaos_level"] == 5

    def test_winner_with_float_finish(self):
        """着順が '1.0'（float 由来）でも正しく認識する。"""
        results = [
            {
                "race_id": "202505021201",
                "records": [
                    {"着順": "1.0", "馬名": "テスト馬", "単勝": "2.5"},
                ],
                "row_count": 1,
            },
        ]
        analysis = analyze_results(results)
        assert analysis["top_horse"] == "テスト馬"


# --------------------------------------------------------------------------- #
# format_post のテスト
# --------------------------------------------------------------------------- #
class TestFormatPost:
    def test_no_data(self):
        assert format_post("20250621", {"has_data": False}) == ""

    def test_basic_format(self):
        analysis = {
            "has_data": True,
            "total_races": 12,
            "upset_count": 2,
            "upsets": [
                {"race_id": "R1", "horse": "テスト馬A", "odds": 25.0},
                {"race_id": "R2", "horse": "テスト馬B", "odds": 12.5},
            ],
            "chaos_level": 3,
            "top_odds": 25.0,
            "top_race": "R1",
            "top_horse": "テスト馬A",
        }
        text = format_post("20250621", analysis)
        assert "6/21(土)" in text
        assert "全12R" in text
        assert "★★★☆☆" in text
        assert "テスト馬A" in text
        assert "25.0倍" in text
        assert "#競馬" in text

    def test_within_length_limit(self):
        analysis = {
            "has_data": True,
            "total_races": 12,
            "upset_count": 3,
            "upsets": [
                {"race_id": f"R{i}", "horse": f"馬{i}", "odds": 20.0 + i}
                for i in range(3)
            ],
            "chaos_level": 4,
            "top_odds": 22.0,
            "top_race": "R2",
            "top_horse": "馬2",
        }
        text = format_post("20250622", analysis)
        assert len(text) <= MAX_POST_LENGTH

    def test_sunday_weekday(self):
        """日曜日が正しく表示される。"""
        analysis = {
            "has_data": True,
            "total_races": 1,
            "upset_count": 0,
            "upsets": [],
            "chaos_level": 1,
            "top_odds": 2.0,
            "top_race": "R1",
            "top_horse": "馬",
        }
        text = format_post("20250622", analysis)
        assert "6/22(日)" in text


# --------------------------------------------------------------------------- #
# ThreadsClient のテスト（API は呼ばない）
# --------------------------------------------------------------------------- #
class TestThreadsClient:
    def test_init_from_env(self, monkeypatch):
        monkeypatch.setenv("THREADS_USER_ID", "12345")
        monkeypatch.setenv("THREADS_ACCESS_TOKEN", "token_abc")
        client = ThreadsClient()
        assert client.user_id == "12345"
        assert client.access_token == "token_abc"

    def test_init_from_args(self):
        client = ThreadsClient(user_id="99", access_token="tok")
        assert client.user_id == "99"
        assert client.access_token == "tok"

    def test_missing_env_raises(self, monkeypatch):
        monkeypatch.delenv("THREADS_USER_ID", raising=False)
        monkeypatch.delenv("THREADS_ACCESS_TOKEN", raising=False)
        with pytest.raises(KeyError):
            ThreadsClient()

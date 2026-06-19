"""Threads 自動投稿モジュール.

毎週土日のレース終了後に、Pegasus-ai でレース結果を取得・分析し、
Meta Threads API を使って投稿する。

必要な環境変数:
    THREADS_USER_ID      : Threads ユーザ ID
    THREADS_ACCESS_TOKEN : Threads API 長期アクセストークン
    PEGASUS_AI_ROOT      : Pegasus-ai リポジトリのパス（mcp_server.py と共通）
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

# --------------------------------------------------------------------------- #
# 定数
# --------------------------------------------------------------------------- #
JST = timezone(timedelta(hours=9))
THREADS_API_BASE = "https://graph.threads.net/v1.0"
MAX_POST_LENGTH = 500  # Threads の文字数上限

# --------------------------------------------------------------------------- #
# Pegasus-ai 接続（mcp_server.py と同じ仕組み）
# --------------------------------------------------------------------------- #
def _pegasus_root() -> Path:
    """Pegasus-ai リポジトリのルートパスを返す。"""
    env = os.environ.get("PEGASUS_AI_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (Path(__file__).resolve().parent.parent / "Pegasus-ai").resolve()


def _ensure_pegasus_on_path() -> Path:
    """Pegasus-ai を import 可能にする。"""
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


# --------------------------------------------------------------------------- #
# Threads API クライアント
# --------------------------------------------------------------------------- #
class ThreadsClient:
    """Meta Threads Publishing API の薄いラッパー。"""

    def __init__(self, user_id: str | None = None, access_token: str | None = None):
        self.user_id = user_id or os.environ["THREADS_USER_ID"]
        self.access_token = access_token or os.environ["THREADS_ACCESS_TOKEN"]

    def post(self, text: str) -> dict[str, Any]:
        """テキスト投稿を作成・公開する。

        Threads API は 2 段階:
          1. メディアコンテナを作成
          2. コンテナを公開
        """
        # ステップ 1: メディアコンテナ作成
        create_url = f"{THREADS_API_BASE}/{self.user_id}/threads"
        create_resp = requests.post(
            create_url,
            data={
                "media_type": "TEXT",
                "text": text[:MAX_POST_LENGTH],
                "access_token": self.access_token,
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        container_id = create_resp.json()["id"]

        # コンテナの処理待ち（最大30秒）
        time.sleep(3)

        # ステップ 2: 公開
        publish_url = f"{THREADS_API_BASE}/{self.user_id}/threads_publish"
        publish_resp = requests.post(
            publish_url,
            data={
                "creation_id": container_id,
                "access_token": self.access_token,
            },
            timeout=30,
        )
        publish_resp.raise_for_status()
        return publish_resp.json()


# --------------------------------------------------------------------------- #
# レースデータ取得・分析
# --------------------------------------------------------------------------- #
def fetch_race_results(date_str: str) -> list[dict[str, Any]]:
    """指定日の全レース結果を取得する。

    Args:
        date_str: YYYYMMDD 形式の開催日。

    Returns:
        各レースの結果辞書のリスト。
    """
    _ensure_pegasus_on_path()
    import collect_race_data as crd

    session = crd.make_session()
    race_ids = crd.get_race_ids(session, date_str)

    results = []
    for race_id in race_ids:
        try:
            df = crd.get_race_result(session, race_id, race_date=date_str)
            if df is not None and len(df) > 0:
                records = json.loads(df.to_json(orient="records", force_ascii=False))
                results.append({
                    "race_id": race_id,
                    "records": records,
                    "row_count": len(records),
                })
        except Exception:
            continue
        time.sleep(1)  # サーバ負荷軽減

    return results


def analyze_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """レース結果を分析し、投稿用のサマリーを返す。

    Args:
        results: fetch_race_results の戻り値。

    Returns:
        分析結果の辞書。
    """
    total_races = len(results)
    if total_races == 0:
        return {"total_races": 0, "has_data": False}

    upsets = []       # 波乱レース（1着が高配当）
    top_odds = 0.0    # 最高単勝オッズ
    top_race = ""     # 最高配当レース
    top_horse = ""    # 最高配当馬

    for race in results:
        records = race["records"]
        # 1着を探す（着順カラム名のバリエーションに対応）
        winner = None
        for r in records:
            finish = r.get("着順") or r.get("finish") or r.get("order_of_finish")
            if str(finish).strip() in ("1", "1.0"):
                winner = r
                break

        if not winner:
            continue

        # 単勝オッズを取得
        odds_val = winner.get("単勝") or winner.get("odds") or winner.get("win_odds") or 0
        try:
            odds = float(str(odds_val).replace(",", ""))
        except (ValueError, TypeError):
            odds = 0.0

        if odds >= 10.0:
            horse_name = winner.get("馬名") or winner.get("horse_name") or "不明"
            upsets.append({
                "race_id": race["race_id"],
                "horse": horse_name,
                "odds": odds,
            })

        if odds > top_odds:
            top_odds = odds
            top_race = race["race_id"]
            top_horse = winner.get("馬名") or winner.get("horse_name") or "不明"

    # 波乱度を 5 段階で算出
    upset_ratio = len(upsets) / total_races if total_races > 0 else 0
    if upset_ratio >= 0.5:
        chaos_level = 5
    elif upset_ratio >= 0.35:
        chaos_level = 4
    elif upset_ratio >= 0.2:
        chaos_level = 3
    elif upset_ratio >= 0.1:
        chaos_level = 2
    else:
        chaos_level = 1

    return {
        "has_data": True,
        "total_races": total_races,
        "upset_count": len(upsets),
        "upsets": upsets,
        "chaos_level": chaos_level,
        "top_odds": top_odds,
        "top_race": top_race,
        "top_horse": top_horse,
    }


# --------------------------------------------------------------------------- #
# 投稿フォーマット
# --------------------------------------------------------------------------- #
def format_post(date_str: str, analysis: dict[str, Any]) -> str:
    """分析結果を Threads 投稿用テキストにフォーマットする。"""
    if not analysis.get("has_data"):
        return ""

    # 日付を見やすく変換
    dt = datetime.strptime(date_str, "%Y%m%d")
    weekday = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
    date_label = f"{dt.month}/{dt.day}({weekday})"

    chaos_stars = "★" * analysis["chaos_level"] + "☆" * (5 - analysis["chaos_level"])

    lines = [
        f"【中央競馬 AI データ分析】{date_label}",
        "",
        f"全{analysis['total_races']}R 分析完了",
        f"波乱度: {chaos_stars}",
    ]

    if analysis["top_odds"] > 0:
        lines.append(f"最高配当: {analysis['top_horse']}（単勝 {analysis['top_odds']:.1f}倍）")

    if analysis["upset_count"] > 0:
        lines.append(f"万馬券級（10倍超）: {analysis['upset_count']}R")

    # 主な波乱レースを最大3件
    top_upsets = sorted(analysis.get("upsets", []), key=lambda x: x["odds"], reverse=True)[:3]
    if top_upsets:
        lines.append("")
        lines.append("注目の高配当:")
        for u in top_upsets:
            lines.append(f"  {u['horse']} {u['odds']:.1f}倍")

    lines.extend([
        "",
        "#競馬 #中央競馬 #AI分析 #データ競馬",
        "by Pegasus-AI",
    ])

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# メインパイプライン
# --------------------------------------------------------------------------- #
def run_pipeline(
    date_str: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """レース結果取得 → 分析 → Threads 投稿のパイプラインを実行する。

    Args:
        date_str: 対象日（YYYYMMDD）。None なら当日。
        dry_run: True なら投稿せずテキストのみ返す。

    Returns:
        実行結果の辞書。
    """
    if date_str is None:
        date_str = datetime.now(JST).strftime("%Y%m%d")

    print(f"[threads_poster] 対象日: {date_str}")

    # 1. レース結果取得
    print("[threads_poster] レース結果を取得中...")
    results = fetch_race_results(date_str)
    print(f"[threads_poster] {len(results)} レース取得完了")

    if not results:
        print("[threads_poster] レース結果がありません。投稿をスキップします。")
        return {"ok": True, "skipped": True, "reason": "レース結果なし"}

    # 2. 分析
    print("[threads_poster] 分析中...")
    analysis = analyze_results(results)

    # 3. 投稿テキスト生成
    post_text = format_post(date_str, analysis)
    print(f"[threads_poster] 投稿テキスト:\n{post_text}")

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "date": date_str,
            "analysis": analysis,
            "post_text": post_text,
        }

    # 4. Threads に投稿
    print("[threads_poster] Threads に投稿中...")
    client = ThreadsClient()
    publish_result = client.post(post_text)
    print(f"[threads_poster] 投稿完了: {publish_result}")

    return {
        "ok": True,
        "date": date_str,
        "analysis": analysis,
        "post_text": post_text,
        "threads_response": publish_result,
    }


def main() -> None:
    """CLI エントリポイント。"""
    import argparse

    parser = argparse.ArgumentParser(description="Threads 自動投稿")
    parser.add_argument("--date", help="対象日 (YYYYMMDD)。省略時は当日。")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずテキストのみ出力")
    args = parser.parse_args()

    result = run_pipeline(date_str=args.date, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

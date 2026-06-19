"""pytest 共通設定.

テスト実行時に本体リポジトリ ``Pegasus-ai`` の場所を環境変数で解決できるようにする。
未設定の場合は本リポジトリの兄弟ディレクトリ ``../Pegasus-ai`` を既定とする。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# mcp_server をテストから import できるようリポジトリルートを sys.path へ追加。
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# PEGASUS_AI_ROOT が未設定なら兄弟ディレクトリを既定値として設定。
os.environ.setdefault(
    "PEGASUS_AI_ROOT",
    str((REPO_ROOT.parent / "Pegasus-ai").resolve()),
)

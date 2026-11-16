from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

# 必须在 import app.* 之前指定隔离的数据目录，避免碰到仓库外的真实库
_TMP = Path(tempfile.mkdtemp(prefix="tiercraft-test-"))
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["FIXTURES_DIR"] = str(Path(__file__).resolve().parents[2] / "fixtures")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import seed  # noqa: E402
from app.services import pipeline  # noqa: E402


@pytest.fixture()
def fresh_db():
    db_file = _TMP / "data" / "app.db"
    if db_file.exists():
        db_file.unlink()
    seed.init_db()
    yield


@pytest.fixture()
def domain_id(fresh_db):
    return pipeline.list_domains()[0]["id"]

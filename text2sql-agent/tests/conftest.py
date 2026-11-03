import pytest

from text2sql import Database
from text2sql.sample_db import build_sample_db


@pytest.fixture(scope="session")
def db(tmp_path_factory):
    path = build_sample_db(tmp_path_factory.mktemp("db") / "shop.db")
    return Database(path)

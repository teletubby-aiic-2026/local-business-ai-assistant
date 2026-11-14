"""시험은 환경 변수에 끌려가지 않고 파일 방식으로 돈다. DB 시험(test_visitors_storage.py)만 자기가 DB 를 정해 쓴다."""
import pytest

from app import storage


@pytest.fixture(autouse=True)
def file_storage_unless_a_test_picks_a_database():
    storage.use(None)
    yield
    storage.reset()

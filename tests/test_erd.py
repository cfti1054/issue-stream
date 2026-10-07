"""docs/ERD.md 가 models.py 와 같은지. 실패하면 `issue-stream erd` 로 다시 만들고 함께 커밋한다."""
from issue_stream import erd


def test_every_table_is_in_a_diagram():
    assert erd.unassigned_tables() == set(), "erd.py 의 DOMAINS 에 새 테이블을 넣으세요"


def test_erd_doc_is_up_to_date():
    assert erd.is_up_to_date(), "docs/ERD.md 가 오래됐습니다 → issue-stream erd"

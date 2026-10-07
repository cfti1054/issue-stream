"""docs/ERD.md 생성기. ERD 는 손으로 그리지 않고 models.py 에서 만든다.

  issue-stream erd           docs/ERD.md 다시 생성
  issue-stream erd --check   models.py 와 어긋나 있으면 실패 (tests/test_erd.py 가 같은 검사를 한다)

모델을 바꾸면 `issue-stream erd` 를 실행하고 docs/ERD.md 를 함께 커밋한다.
GitHub 에서 열면 Mermaid 다이어그램이 그림으로 보인다.
"""
from __future__ import annotations

import inspect

from sqlalchemy import Column, Table
from sqlalchemy.dialects import postgresql

from .core.config import ROOT_DIR
from .db import models
from .db.sequences import ENTITY_TABLES

ERD_PATH = ROOT_DIR / "docs" / "ERD.md"

# 영역별 다이어그램. 새 테이블은 반드시 한 곳에 넣는다 (tests/test_erd.py 가 검사)
DOMAINS: list[tuple[str, str, list[str]]] = [
    ("account", "계정·관심종목", ["users", "user_sessions", "user_watchlist", "tickers"]),
    ("news", "뉴스·이슈", ["articles", "article_bodies", "issues", "issue_articles", "issue_tickers",
                         "issue_summaries", "tickers"]),
    ("market", "시세·지표", ["tickers", "prices", "dart_corp_codes", "sector_indices", "macro_series"]),
    ("ops", "운영", ["job_runs", "api_usage"]),
]

# FK 는 없지만 값으로 이어지는 관계 (점선으로 표시)
LOGICAL: list[tuple[str, str, str]] = [
    ("tickers", "prices", "symbol = code (지수 심볼도 들어가 FK 없음)"),
    ("tickers", "dart_corp_codes", "stock_code = code"),
]

_PG = postgresql.dialect()
_TYPE_ALIAS = {"TIMESTAMP WITH TIME ZONE": "timestamptz", "DOUBLE PRECISION": "float8"}


def _type(c: Column) -> str:
    t = c.type.compile(dialect=_PG)
    return _TYPE_ALIAS.get(t, t).lower().replace(" ", "_")


def _keys(t: Table, c: Column) -> list[str]:
    keys = []
    if c.primary_key:
        keys.append("PK")
    if c.foreign_keys:
        keys.append("FK")
    unique_idx = any(ix.unique and list(ix.columns) == [c] for ix in t.indexes)
    if not c.primary_key and (c.unique or unique_idx):
        keys.append("UK")
    return keys


def _default(t: Table, c: Column) -> str:
    if t.name in ENTITY_TABLES and c.name in ("id", "no"):
        return f"nextval('seq_{t.name}_{c.name}')"
    if c.default is not None and getattr(c.default, "is_scalar", False):
        return repr(c.default.arg)
    if c.default is not None and getattr(c.default, "is_callable", False):
        return "(앱에서 계산)"
    return ""


def _nullable(t: Table, c: Column) -> bool:
    if t.name in ENTITY_TABLES and c.name == "no":
        return False   # SQLite 트리거 때문에 정의는 NULL 허용이지만 PG 는 NOT NULL
    return bool(c.nullable) and not c.primary_key


def _cardinality(child: Table, fk_col: Column) -> str:
    """부모 → 자식 관계 기호. FK 하나가 자식의 PK 전체면 1:1."""
    one_to_one = list(child.primary_key.columns) == [fk_col]
    parent_side = "|o" if fk_col.nullable and not fk_col.primary_key else "||"
    return f"{parent_side}--o|" if one_to_one else f"{parent_side}--o{{"


def _relations(tables: set[str]) -> list[str]:
    out = []
    for name in sorted(tables):
        t = models.Base.metadata.tables[name]
        for c in t.columns:
            for fk in c.foreign_keys:
                parent = fk.column.table.name
                if parent in tables:
                    label = f"{c.name} → {parent}.{fk.column.name}"
                    out.append(f'    {parent} {_cardinality(t, c)} {name} : "{label}"')
    for parent, child, label in LOGICAL:
        if parent in tables and child in tables:
            out.append(f'    {parent} ||..o{{ {child} : "{label}"')
    return out


def _entity(t: Table) -> list[str]:
    lines = [f"    {t.name} {{"]
    for c in t.columns:
        keys = ", ".join(_keys(t, c))
        lines.append(f"        {_type(c)} {c.name}{' ' + keys if keys else ''}")
    lines.append("    }")
    return lines


def _model_doc(t: Table) -> str:
    for m in models.Base.registry.mappers:
        if m.local_table is t:
            doc = inspect.getdoc(m.class_) or ""
            return " ".join(doc.split("\n\n")[0].split())
    return ""


def _detail(t: Table) -> list[str]:
    out = [f"### `{t.name}`", ""]
    if doc := _model_doc(t):
        out += [doc, ""]
    out += ["| 컬럼 | 타입 | 키 | NULL | 기본값 | 참조 | 설명 |", "|---|---|---|---|---|---|---|"]
    for c in t.columns:
        ref = ", ".join(f"{fk.column.table.name}.{fk.column.name}"
                        + (f" ({fk.ondelete})" if fk.ondelete else "") for fk in c.foreign_keys)
        out.append(f"| `{c.name}` | {_type(c)} | {' '.join(_keys(t, c))} | {'Y' if _nullable(t, c) else ''} "
                   f"| {_default(t, c)} | {ref} | {c.comment or ''} |")
    # 집합이라 순서가 매번 달라질 수 있어 정렬한다 (ERD.md 가 실행마다 바뀌지 않도록)
    def cols(x) -> str:
        return ", ".join(c.name for c in x.columns)
    multi = sorted((ix for ix in t.indexes if len(ix.columns) > 1 or not ix.unique), key=cols)
    uniq = sorted((cons for cons in t.constraints
                   if cons.__class__.__name__ == "UniqueConstraint" and len(cons.columns) > 1), key=cols)
    extras = [f"UNIQUE ({cols(u)})" for u in uniq]
    extras += [f"{'UNIQUE ' if ix.unique else ''}INDEX ({cols(ix)})" for ix in multi]
    if extras:
        out += ["", "제약·인덱스: " + " · ".join(extras)]
    return out + [""]


def render() -> str:
    md = models.Base.metadata
    lines = [
        "# DB ERD",
        "",
        "> **자동 생성 문서 — 직접 고치지 마세요.** `src/issue_stream/db/models.py` 를 바꾼 뒤",
        "> `issue-stream erd` 로 다시 만들고 함께 커밋합니다. 어긋나면 `pytest` 가 실패합니다.",
        "",
        "- 타입은 PostgreSQL 기준. SQLite 에서도 같은 구조로 만들어진다 (bigint PK → INTEGER 자동 증가).",
        f"- **id / no**: {', '.join(f'`{t}`' for t in ENTITY_TABLES)} 의 `id` 는 내부 PK"
        " (시퀀스 `seq_<테이블>_id`, FK 는 이 값만 참조), `no` 는 화면·API 에 보이는 번호"
        " (시퀀스 `seq_<테이블>_no`, UNIQUE).",
        "- 매핑 테이블(`user_watchlist`, `issue_articles`, `issue_tickers`)은 시퀀스 없이 FK 복합키.",
        "- 실선 = FK, 점선 = FK 없는 논리 관계.",
        "",
        "## 목차",
        "",
    ]
    lines += [f"- [{title}](#{title.replace('·', '')})" for _, title, _ in DOMAINS]
    lines += ["- [테이블 상세](#테이블-상세)", "- [시퀀스](#시퀀스)", ""]
    for _key, title, names in DOMAINS:
        lines += [f"## {title}", "", "```mermaid", "erDiagram"]
        for name in names:
            lines += _entity(md.tables[name])
        lines += _relations(set(names))
        lines += ["```", ""]
    lines += ["## 테이블 상세", ""]
    seen = []
    for _key, _title, names in DOMAINS:
        seen += [n for n in names if n not in seen]
    for name in seen:
        lines += _detail(md.tables[name])
    lines += ["## 시퀀스", "", "| 시퀀스 | 대상 | PostgreSQL | SQLite |", "|---|---|---|---|"]
    for t in ENTITY_TABLES:
        lines.append(f"| `seq_{t}_id` | `{t}.id` | DEFAULT nextval, OWNED BY | INTEGER PRIMARY KEY 자동 증가 |")
        lines.append(f"| `seq_{t}_no` | `{t}.no` | DEFAULT nextval, OWNED BY, NOT NULL | 트리거 `trg_{t}_no` (MAX+1) |")
    return "\n".join(lines) + "\n"


def unassigned_tables() -> set[str]:
    listed = {n for _, _, names in DOMAINS for n in names}
    return set(models.Base.metadata.tables) - listed


def is_up_to_date() -> bool:
    if not ERD_PATH.exists():
        return False
    return ERD_PATH.read_text(encoding="utf-8").replace("\r\n", "\n") == render()


def write() -> None:
    ERD_PATH.write_text(render(), encoding="utf-8", newline="\n")

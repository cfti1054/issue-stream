from logging.config import fileConfig

from alembic import context

from issue_stream.db.session import get_engine, resolve_url
from issue_stream.db.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", resolve_url().replace("%", "%%"))
# 앱 안에서 실행할 때(serve·migrate)는 앱 로깅 설정을 건드리지 않는다
if config.config_file_name and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    # 앱과 같은 엔진을 쓴다 (SQLite 폴더 생성·PRAGMA 설정 포함)
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

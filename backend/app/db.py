import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.environ.get("HIREMODUS_DATABASE_URL", "sqlite:///./hiremodus.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def add_missing_columns():
    """Lightweight upgrade for databases created by an earlier HireModus version: add new nullable columns."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    ddl = col.type.compile(dialect=engine.dialect)
                    default = ""
                    if col.default is not None and getattr(col.default, "is_scalar", False):
                        v = col.default.arg
                        if isinstance(v, bool):
                            default = f" DEFAULT {'TRUE' if v else 'FALSE'}" if engine.dialect.name != "sqlite" else f" DEFAULT {int(v)}"
                        elif isinstance(v, (int, float)):
                            default = f" DEFAULT {v}"
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}{default}'))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

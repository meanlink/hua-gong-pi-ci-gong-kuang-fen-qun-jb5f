from sqlalchemy import inspect, text
from src.config.database import engine
from src import models
from src.config.database import Base


def _ensure_columns():
    """create_all 只建新表，不会给已存在的表补列；这里做幂等补列。"""
    inspector = inspect(engine)
    existing = {table: {col['name'] for col in inspector.get_columns(table)}
                for table in inspector.get_table_names()}
    with engine.begin() as conn:
        if 'jobs' in existing and 'blind_lock_id' not in existing['jobs']:
            conn.execute(text('ALTER TABLE jobs ADD COLUMN blind_lock_id INTEGER NULL'))


def migrate():
    Base.metadata.create_all(engine)
    _ensure_columns()


if __name__ == '__main__':
    migrate()

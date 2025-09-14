from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from core.settings import get_settings


settings = get_settings()
engine = sa.create_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Any:
    with SessionLocal() as session:
        yield session


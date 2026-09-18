from __future__ import annotations

import os

os.environ.setdefault("API_SECRET_KEY", "test-only-secret-key-never-use-in-production-12345")
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

# Register JSONB compiler for SQLite globally for all tests
@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

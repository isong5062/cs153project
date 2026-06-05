"""Reusable column types."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSONB on Postgres, plain JSON elsewhere (e.g. SQLite).
JSONVariant = JSON().with_variant(JSONB, "postgresql")

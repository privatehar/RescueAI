"""Declarative base, constraint naming convention and small column helpers."""

from enum import StrEnum

from sqlalchemy import Enum, MetaData
from sqlalchemy.orm import DeclarativeBase

# Deterministic constraint/index names. Without this, PostgreSQL invents names and Alembic
# cannot reliably drop or alter constraints later. "ck" embeds the name we give each CHECK.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def enum_column(enum_cls: type[StrEnum], length: int) -> Enum:
    """Store a StrEnum as VARCHAR (its *values*), not as a native PostgreSQL ENUM type.

    Native enums need ``ALTER TYPE`` to add a value, which is awkward inside migrations. A
    VARCHAR plus a named CHECK constraint (see ``in_list``) gives the same integrity.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [member.value for member in e],
        validate_strings=True,
    )


def in_list(column: str, enum_cls: type[StrEnum]) -> str:
    """SQL text for a CHECK that ``column`` only holds values of ``enum_cls``."""
    values = ", ".join(f"'{member.value}'" for member in enum_cls)
    return f"{column} IN ({values})"

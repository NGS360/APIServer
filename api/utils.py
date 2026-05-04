"""Shared utilities for the API layer."""

from __future__ import annotations

from typing import Sequence

from fastapi import HTTPException, status


def check_duplicate_attribute_keys(
    attributes: Sequence,
    entity_name: str = "attributes",
) -> None:
    """Raise HTTP 400 if any attribute keys collide case-insensitively.

    This mirrors MySQL's default (case-insensitive) collation behaviour
    for ``UniqueConstraint("..._id", "key")`` on attribute tables.

    Args:
        attributes: Sequence of objects with a ``.key`` attribute
            (e.g. ``Attribute``, ``SampleCreate.attributes``).
        entity_name: Label used in the error message, e.g.
            ``"project attributes"`` or ``"sample attributes"``.

    Raises:
        HTTPException: 400 with a detail listing the duplicate keys.
    """
    seen: set[str] = set()
    keys = [attr.key for attr in attributes]
    dups = [k for k in keys if k.lower() in seen or seen.add(k.lower())]
    if dups:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Duplicate keys ({', '.join(dups)}) are not "
                f"allowed in {entity_name}."
            ),
        )

from __future__ import annotations


def quote_identifier(identifier: str) -> str:
    escaped_identifier = identifier.replace('"', '""')
    return f'"{escaped_identifier}"'


def strip_trailing_query_semicolon(query: str) -> str:
    return query.strip().rstrip(";").strip()

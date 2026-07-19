"""Single-table key builders for the `language-memory` DynamoDB table."""


def pk(user_id: str, lang: str) -> str:
    return f"USER#{user_id}#LANG#{lang}"


def concept_sk(cid: str) -> str:
    return f"CONCEPT#{cid}"


def item_sk(cid: str, facet: str) -> str:
    return f"ITEM#{cid}#{facet}"


def log_sk(cid: str, facet: str, iso_timestamp: str) -> str:
    return f"LOG#{cid}#{facet}#{iso_timestamp}"


PROFILE_SK = "PROFILE"


def queue_key_due(due: str) -> str:
    """GSI1 sort key for a scheduled item; `due` is an ISO datetime (UTC).
    ISO format sorts lexicographically, so range queries are exact."""
    return f"DUE#{due}"


def queue_key_new(priority: int, cid: str) -> str:
    """GSI1 sort key for a backlog item.

    The concept_id suffix only makes drip order deterministic between
    equal priorities; queries use begins_with("NEW#").
    """
    return f"NEW#{priority:05d}#{cid}"


def item_id(cid: str, facet: str) -> str:
    """Public item identifier used in the MCP contract, e.g. `a3f9e1b2c4d5#production`."""
    return f"{cid}#{facet}"


def parse_item_id(value: str) -> tuple[str, str]:
    """Split an item_id into (concept_id, facet). Raises ValueError on malformed input."""
    cid, sep, facet = value.partition("#")
    if not sep or not cid or not facet or "#" in facet:
        raise ValueError(f"malformed item_id: {value!r}")
    return cid, facet

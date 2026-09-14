"""Named response checks shared by filter component scenarios."""
import json
from collections.abc import Callable

from django.http import HttpResponse


def response_is_list(resp: HttpResponse) -> bool:
    return isinstance(json.loads(resp.content), list)


def response_is_empty(resp: HttpResponse) -> bool:
    return json.loads(resp.content) == []


def response_has_lookup_metadata(resp: HttpResponse) -> bool:
    lookups = json.loads(resp.content)
    return isinstance(lookups, list) and bool(lookups) and all(
        isinstance(lookup, dict)
        and set(lookup) == {"id", "label", "nested"}
        and isinstance(lookup["id"], str)
        and isinstance(lookup["label"], str)
        and isinstance(lookup["nested"], bool)
        for lookup in lookups
    ) and len({lookup["id"] for lookup in lookups}) == len(lookups)


def response_contains_lookup(lookup_id: str, *, nested: bool) -> Callable[[HttpResponse], bool]:
    def contains_lookup(resp: HttpResponse) -> bool:
        return any(
            lookup["id"] == lookup_id and lookup["nested"] is nested
            for lookup in json.loads(resp.content)
        )

    contains_lookup.__name__ = f"response_contains_lookup({lookup_id!r}, nested={nested})"
    return contains_lookup


def response_excludes_lookup(lookup_id: str) -> Callable[[HttpResponse], bool]:
    def excludes_lookup(resp: HttpResponse) -> bool:
        return all(lookup["id"] != lookup_id for lookup in json.loads(resp.content))

    excludes_lookup.__name__ = f"response_excludes_lookup({lookup_id!r})"
    return excludes_lookup


def response_has_widget(resp: HttpResponse) -> bool:
    payload = json.loads(resp.content)
    return isinstance(payload, dict) and isinstance(payload.get("widget"), str) and bool(payload["widget"])


def widget_has_input(**attributes: str | bool) -> Callable[[HttpResponse], bool]:
    """Match parsed input attributes; booleans check attribute presence/absence."""
    from html.parser import HTMLParser

    class InputParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inputs = []

        def handle_starttag(self, tag, attrs):
            if tag == "input":
                self.inputs.append(dict(attrs))

    def matches_input(resp: HttpResponse) -> bool:
        parser = InputParser()
        parser.feed(json.loads(resp.content)["widget"])
        return any(
            all(
                ((key in actual) is expected) if isinstance(expected, bool)
                else actual.get(key) == expected
                for key, expected in attributes.items()
            )
            for actual in parser.inputs
        )

    matches_input.__name__ = f"widget_has_input({attributes!r})"
    return matches_input

"""
The global search component is a powerful tool that allows users to quickly navigate
to different parts of the application as well as search for specific content.

It works by analyzing the different search prefixes and then performing
the appropriate search based on the prefix used.

Prefixes:
- No prefix: General search. This allows users to search for content across the application.

- ">":  Search for routes. This allows users to quickly navigate to different parts of the application by typing the name
        of the route they want to go to. If the user adds ? at the end of a query (e.g. ">dashboard?first_name=david"), the search will include those query parameters in the search results.
        The same applies for # to include fragments in the search results (e.g. ">dashboard#section1").

- "@":  Search for users. This allows users to quickly find other users in the system by typing their name or username.

- "!":  Actions. This allows users to quickly perform actions by typing the name of the action they want to perform. (Not implemented yet)

- "/":  Module and model search. This allows users to do a more targeted search by specifying the module and model they want to search in
        Patterns:
            - /<module_code>//<string_query>: Search for all content within a specific module. Since the model is not specified, the search will include all models within that module.
            - //<model_name>/<string_query>: Search for all content related to a specific model across all modules. The result will include the module name in the search results to differentiate between different modules that have the same model.
            - /<module_code>/<model_name>/<string_query>: Search for all content related to a specific
            - ///: Same as general search
        Note: ? can be used for filtering the search results based on query parameters (e.g. "/sales/customer/<string_query>?first_name=david")

"""

from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse

from bloomerp.modules.definition import module_registry
from bloomerp.router import router
from bloomerp.services.search_services import (
    ObjectSearchResult,
    SearchManager,
    _normalize_key,
)

# -------------------------------
# Helper functions
# -------------------------------


def _split_query_and_suffix(value: str) -> tuple[str, str]:
    """Separate route search text from optional URL parameters and fragments."""
    value = value.strip()
    if not value:
        return "", ""

    question_idx = value.find("?")
    hash_idx = value.find("#")
    candidates = [idx for idx in [question_idx, hash_idx] if idx != -1]
    if not candidates:
        return value.strip(), ""

    split_idx = min(candidates)
    return value[:split_idx].strip(), value[split_idx:].strip()


def _collect_object_results(result: ObjectSearchResult) -> list[dict[str, Any]]:
    """Adapt shared search objects to the existing grouped template contract."""
    groups: dict[type[Model], dict[str, Any]] = {}
    for obj in result.items:
        model = type(obj)
        if model not in groups:
            module = module_registry.get_module_for_model(model)
            groups[model] = {
                "model_label": model._meta.verbose_name_plural.title(),
                "module_labels": [
                    item.localized_name
                    for item in module_registry.get_lineage(module.full_id or module.id)
                ]
                if module
                else [],
                "objects": [],
                "detail_routes": router.filter(route_type="detail", model=model),
            }
        groups[model]["objects"].append(obj)
    return list(groups.values())


@router.register(path="components/global_search/", name="components_global_search")
@login_required
def global_search(request: HttpRequest) -> HttpResponse:
    """
    Component that is used for global search.

    Args:
        request (HttpRequest): the request object

    GET parameters:
        q (str): the search query entered by the user. This is expected to include a

    Returns:
        HttpResponse: the response object containing the rendered global search results
    """
    query = request.GET.get("q", "")
    trimmed_query = (query or "").strip()
    if not trimmed_query:
        return HttpResponse("")

    starts_with = trimmed_query[0]
    search_query = trimmed_query

    PER_MODEL_LIMIT = 5
    TOTAL_LIMIT = 20
    ROUTE_LIMIT = 12
    USER_LIMIT = 8

    context = {
        "query": trimmed_query,
        "search_type": "general",
        "search_label": "All content",
        "highlight_query": trimmed_query,
        "route_results": [],
        "user_results": [],
        "object_results": [],
        "results_truncated": False,
        "results_limit": TOTAL_LIMIT,
        "slash_search_skipped": False,
        "slash_error": None,
        "search_scope": {},
    }

    match starts_with:
        case ">":
            search_query = trimmed_query[1:].strip()
            base_query, suffix = _split_query_and_suffix(search_query)
            context["search_type"] = "routes"
            context["search_label"] = "Routes"
            context["highlight_query"] = base_query
            context["query"] = base_query

            if base_query:
                matched_routes = []
                for route in router.get_routes():
                    if not route.searchable:
                        continue

                    # We don't want to include routes that require arguments in the global search, as they cannot be directly navigated to without additional input. This is because the global search is designed for quick navigation, and including routes with required arguments could lead to confusion or dead ends in the search results.
                    if route.nr_of_args() > 0:
                        continue

                    route_name = route.localized_name
                    route_desc = route.localized_description
                    route_path = route.path or ""
                    route_search_text = " ".join(
                        [route_name, route_desc, route.url_name or "", route_path]
                    )
                    if _normalize_key(base_query) not in _normalize_key(
                        route_search_text
                    ):
                        continue

                    route_url = None
                    if "<" not in route_path and ">" not in route_path:
                        try:
                            route_url = reverse(route.url_name)
                        except NoReverseMatch:
                            route_url = None

                    if route_url and suffix:
                        route_url = f"{route_url}{suffix}"

                    matched_routes.append(
                        {
                            "name": route_name,
                            "path": route_path,
                            "description": route_desc,
                            "url": route_url,
                            "module": route.module.localized_name
                            if route.module
                            else None,
                        }
                    )

                    if len(matched_routes) >= ROUTE_LIMIT:
                        context["results_truncated"] = True
                        break

                context["route_results"] = matched_routes

        case _:
            user_search = trimmed_query.startswith("@")
            result = SearchManager(request.user).search_objects(
                trimmed_query,
                per_model_limit=USER_LIMIT if user_search else PER_MODEL_LIMIT,
                total_limit=USER_LIMIT if user_search else TOTAL_LIMIT,
            )
            context.update(
                {
                    "search_type": result.search.search_type,
                    "search_label": result.search.label,
                    "highlight_query": result.search.value,
                    "query": result.search.value,
                    "search_scope": result.search.scope,
                    "slash_error": result.search.error,
                    "results_truncated": result.limit_reached,
                }
            )
            if result.search.search_type == "users":
                context["user_results"] = [
                    {"user": user, "display": user.get_full_name() or user.username}
                    for user in result.items
                ]
            else:
                context["object_results"] = _collect_object_results(result)

    return render(request, "components/search/global_search.html", context)

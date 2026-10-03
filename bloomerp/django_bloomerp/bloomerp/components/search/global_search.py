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

import unicodedata
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils.encoding import force_str

from bloomerp.modules.definition import ModuleConfig, module_registry
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager
from bloomerp.router import router
from bloomerp.services.search_services import SearchManager

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


def _normalize_key(value: str) -> str:
    """Normalize localized search keys for case-insensitive prefix matching."""
    normalized = unicodedata.normalize("NFKC", force_str(value or ""))
    return normalized.strip().casefold().replace("-", "_")


def _ensure_module_registry_models() -> None:
    """Ensure dynamic models are mapped into the registry before scoped search."""
    try:
        module_registry._register_models_from_apps()
    except Exception:  # noqa: BLE001 - preserve the registry refresh fallback
        module_registry.refresh()


def _resolve_module(module_key: str) -> ModuleConfig | None:
    """Resolve a module by identifier, code or localized name, including prefixes."""
    _ensure_module_registry_models()
    normalized = _normalize_key(module_key)
    module = module_registry.get(normalized)
    if module:
        return module
    exact_matches = []
    partial_matches = []
    for item in module_registry.get_all().values():
        code = _normalize_key(item.code)
        name = _normalize_key(item.name)
        localized_name = _normalize_key(item.localized_name)
        module_id = _normalize_key(item.full_id or item.id)
        if normalized in {code, name, localized_name, module_id}:
            exact_matches.append(item)
        elif any(
            value.startswith(normalized)
            for value in (code, name, localized_name, module_id)
        ):
            partial_matches.append(item)
    if exact_matches:
        return exact_matches[0]
    if partial_matches:
        return partial_matches[0]
    return None


def _resolve_models_by_name(
    model_key: str, permission_manager: UserPolicyManager
) -> list[type[Model]]:
    """Resolve localized and partial model names within the user's accessible models."""
    _ensure_module_registry_models()
    normalized = _normalize_key(model_key)
    matched = []
    for model in permission_manager.get_accessible_models(BloomerpPermission.VIEW):
        model_name = _normalize_key(model._meta.model_name)
        verbose_name = _normalize_key(model._meta.verbose_name)
        verbose_name_plural = _normalize_key(model._meta.verbose_name_plural)
        if (
            model_name == normalized
            or verbose_name == normalized
            or verbose_name_plural == normalized
            or model_name.startswith(normalized)
            or verbose_name.startswith(normalized)
            or verbose_name_plural.startswith(normalized)
        ):
            matched.append(model)
    return matched


def _collect_object_results(
    request: HttpRequest,
    models: list[type[Model]],
    search_value: str,
    per_model_limit: int,
    total_limit: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Adapt shared search results to the existing grouped template contract."""
    result = SearchManager(request.user).search_objects(
        search_value,
        models=models,
        per_model_limit=per_model_limit,
        total_limit=total_limit,
    )
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
    return list(groups.values()), result.limit_reached


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

    permission_manager = UserPolicyManager(request.user)

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

        case "@":
            search_query = trimmed_query[1:].strip()
            context["search_type"] = "users"
            context["search_label"] = "Users"
            context["highlight_query"] = search_query
            context["query"] = search_query

            if search_query:
                user_model = get_user_model()
                result = SearchManager(request.user).search_objects(
                    search_query,
                    models=[user_model],
                    per_model_limit=USER_LIMIT,
                    total_limit=USER_LIMIT,
                )
                context["results_truncated"] = result.limit_reached
                context["user_results"] = [
                    {"user": user, "display": user.get_full_name() or user.username}
                    for user in result.items
                ]

        case "/":
            search_query = trimmed_query
            context["search_type"] = "slash"
            context["search_label"] = "Module and model"
            context["highlight_query"] = search_query
            context["query"] = search_query
            context["slash_error"] = None
            context["search_scope"] = {}

            if search_query.startswith("///"):
                search_value = search_query[3:].strip()
                models = permission_manager.get_accessible_models(
                    BloomerpPermission.VIEW
                )
                context["search_label"] = "All content"
                context["highlight_query"] = search_value
                context["query"] = search_value
                context["object_results"], truncated = _collect_object_results(
                    request,
                    models,
                    search_value,
                    PER_MODEL_LIMIT,
                    TOTAL_LIMIT,
                )
                context["results_truncated"] = context["results_truncated"] or truncated
            elif search_query.startswith("//"):
                remainder = search_query[2:]
                model_key, _, search_value = remainder.partition("/")
                context["search_label"] = "Model search"
                context["search_scope"] = {"model": model_key}
                models = _resolve_models_by_name(model_key, permission_manager)
                context["highlight_query"] = search_value
                context["query"] = search_value
                if not models:
                    context["slash_error"] = "Model not found."
                else:
                    context["object_results"], truncated = _collect_object_results(
                        request,
                        models,
                        search_value,
                        PER_MODEL_LIMIT,
                        TOTAL_LIMIT,
                    )
                    context["results_truncated"] = (
                        context["results_truncated"] or truncated
                    )
            else:
                remainder = search_query[1:]
                if "//" in remainder:
                    module_key, _, search_value = remainder.partition("//")
                    module = _resolve_module(module_key)
                    context["search_label"] = "Module search"
                    context["search_scope"] = {"module": module_key}
                    context["highlight_query"] = search_value
                    context["query"] = search_value
                    if not module:
                        context["slash_error"] = "Module not found."
                    else:
                        context["search_scope"] = {"module": module.localized_name}
                        models = module_registry.get_models_for_module(
                            module.id, include_descendants=True
                        )
                        context["object_results"], truncated = _collect_object_results(
                            request,
                            models,
                            search_value,
                            PER_MODEL_LIMIT,
                            TOTAL_LIMIT,
                        )
                        context["results_truncated"] = (
                            context["results_truncated"] or truncated
                        )
                else:
                    parts = [part for part in remainder.split("/") if part]
                    if len(parts) >= 3:
                        module_key = parts[0]
                        model_key = parts[1]
                        search_value = "/".join(parts[2:]).strip()
                        module = _resolve_module(module_key)
                        context["search_label"] = "Module and model"
                        context["search_scope"] = {
                            "module": module_key,
                            "model": model_key,
                        }
                        context["highlight_query"] = search_value
                        context["query"] = search_value
                        if not module:
                            context["slash_error"] = "Module not found."
                        else:
                            models = _resolve_models_by_name(
                                model_key, permission_manager
                            )
                            models = [
                                model
                                for model in models
                                if model
                                in module_registry.get_models_for_module(
                                    module.id, include_descendants=True
                                )
                            ]
                            context["search_scope"] = {
                                "module": module.localized_name,
                                "model": model_key,
                            }
                            if not models:
                                context["slash_error"] = "Model not found in module."
                            else:
                                context["object_results"], truncated = (
                                    _collect_object_results(
                                        request,
                                        models,
                                        search_value,
                                        PER_MODEL_LIMIT,
                                        TOTAL_LIMIT,
                                    )
                                )
                                context["results_truncated"] = (
                                    context["results_truncated"] or truncated
                                )
                    else:
                        context["slash_error"] = (
                            "Use /<module>//<query>, //<model>/<query>, or /<module>/<model>/<query>."
                        )

        case _:
            search_query = trimmed_query
            context["search_type"] = "general"
            context["search_label"] = "All content"
            context["highlight_query"] = search_query
            context["query"] = search_query

            if search_query:
                models = permission_manager.get_accessible_models(
                    BloomerpPermission.VIEW
                )
                context["object_results"], truncated = _collect_object_results(
                    request,
                    models,
                    search_query,
                    PER_MODEL_LIMIT,
                    TOTAL_LIMIT,
                )
                context["results_truncated"] = context["results_truncated"] or truncated

    return render(request, "components/search/global_search.html", context)

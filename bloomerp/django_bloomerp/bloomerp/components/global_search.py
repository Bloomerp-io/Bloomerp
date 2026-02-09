from django.shortcuts import render
from django.http import HttpRequest, HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.urls import NoReverseMatch

from bloomerp.router import router
from bloomerp.modules.definition import module_registry
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.utils.models import string_search_queryset

# -------------------------------
# Helper functions
# -------------------------------

def _split_query_and_suffix(value: str) -> tuple[str, str]:
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
    return (value or "").strip().lower().replace("-", "_")

def _resolve_module(module_key: str):
    normalized = _normalize_key(module_key)
    module = module_registry.get(normalized)
    if module:
        return module
    for item in module_registry.get_all().values():
        if _normalize_key(item.code) == normalized or _normalize_key(item.name) == normalized:
            return item
    return None

def _resolve_models_by_name(model_key: str) -> list:
    normalized = _normalize_key(model_key)
    matched = []
    for module in module_registry.get_all().values():
        for model in module_registry.get_models_for_module(module.id):
            if _normalize_key(model._meta.model_name) == normalized:
                matched.append(model)
                continue
            if _normalize_key(model._meta.verbose_name) == normalized:
                matched.append(model)
                continue
            if _normalize_key(model._meta.verbose_name_plural) == normalized:
                matched.append(model)
    return matched

def _collect_object_results(
    request: HttpRequest,
    permission_manager: UserPermissionManager,
    models: list,
    search_value: str,
    per_model_limit: int,
    total_limit: int,
) -> tuple[list, bool]:
    results = []
    total_results = 0
    truncated = False

    if not search_value:
        return results, truncated

    for model in models:
        if not model or model == ContentType:
            continue

        permission_name = f"{model._meta.app_label}.view_{model._meta.model_name}"
        if not (request.user.has_perm(permission_name) or request.user.is_superuser):
            continue

        content_type = ContentType.objects.get_for_model(model)
        row_policies_exist = permission_manager.get_row_policies().filter(
            content_type=content_type
        ).exists()

        if row_policies_exist:
            base_qs = permission_manager.get_queryset(model, f"view_{model._meta.model_name}")
        else:
            base_qs = model.objects.all()

        remaining_slots = total_limit - total_results
        if remaining_slots <= 0:
            truncated = True
            break

        matching_objects = list(
            string_search_queryset(base_qs, search_value)[: per_model_limit + 1]
        )
        if not matching_objects:
            continue

        if len(matching_objects) > per_model_limit:
            truncated = True
            matching_objects = matching_objects[:per_model_limit]

        if len(matching_objects) > remaining_slots:
            truncated = True
            matching_objects = matching_objects[:remaining_slots]

        modules = module_registry.get_modules_for_model(model)
        results.append(
            {
                "model_label": model._meta.verbose_name_plural.title(),
                "module_labels": [module.name for module in modules] if modules else [],
                "objects": matching_objects,
            }
        )

        total_results += len(matching_objects)
        if total_results >= total_limit:
            truncated = True
            break

    return results, truncated


@router.register(path='components/global_search/', name='components_global_search')
@login_required
def global_search(request: HttpRequest) -> HttpResponse:
    """
    Component that is used for global search.
    
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

    permission_manager = UserPermissionManager(request.user)

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
                    if route.name.startswith("components_"):
                        continue

                    route_name = route.name or ""
                    route_desc = route.description or ""
                    route_path = route.path or ""
                    if base_query.lower() not in f"{route_name} {route_desc} {route_path}".lower():
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
                            "module": route.module.name if route.module else None,
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
                model_name = user_model._meta.model_name
                permission_name = f"{user_model._meta.app_label}.view_{model_name}"
                if request.user.has_perm(permission_name) or request.user.is_superuser:
                    content_type = ContentType.objects.get_for_model(user_model)
                    row_policies_exist = permission_manager.get_row_policies().filter(
                        content_type=content_type
                    ).exists()

                    if row_policies_exist:
                        base_qs = permission_manager.get_queryset(user_model, f"view_{model_name}")
                    else:
                        base_qs = user_model.objects.all()

                    results = list(string_search_queryset(base_qs, search_query)[: USER_LIMIT + 1])
                    if len(results) > USER_LIMIT:
                        context["results_truncated"] = True
                        results = results[:USER_LIMIT]

                    context["user_results"] = [
                        {
                            "user": user,
                            "display": user.get_full_name() or user.username,
                        }
                        for user in results
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
                models = [
                    content_type.model_class()
                    for content_type in request.user.accessible_content_types
                ]
                context["search_label"] = "All content"
                context["highlight_query"] = search_value
                context["query"] = search_value
                context["object_results"], truncated = _collect_object_results(
                    request,
                    permission_manager,
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
                models = _resolve_models_by_name(model_key)
                context["highlight_query"] = search_value
                context["query"] = search_value
                if not models:
                    context["slash_error"] = "Model not found."
                else:
                    context["object_results"], truncated = _collect_object_results(
                        request,
                        permission_manager,
                        models,
                        search_value,
                        PER_MODEL_LIMIT,
                        TOTAL_LIMIT,
                    )
                    context["results_truncated"] = context["results_truncated"] or truncated
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
                        context["search_scope"] = {"module": module.name}
                        models = module_registry.get_models_for_module(module.id)
                        context["object_results"], truncated = _collect_object_results(
                            request,
                            permission_manager,
                            models,
                            search_value,
                            PER_MODEL_LIMIT,
                            TOTAL_LIMIT,
                        )
                        context["results_truncated"] = context["results_truncated"] or truncated
                else:
                    parts = [part for part in remainder.split("/") if part]
                    if len(parts) >= 3:
                        module_key = parts[0]
                        model_key = parts[1]
                        search_value = "/".join(parts[2:]).strip()
                        module = _resolve_module(module_key)
                        context["search_label"] = "Module and model"
                        context["search_scope"] = {"module": module_key, "model": model_key}
                        context["highlight_query"] = search_value
                        context["query"] = search_value
                        if not module:
                            context["slash_error"] = "Module not found."
                        else:
                            models = _resolve_models_by_name(model_key)
                            models = [
                                model
                                for model in models
                                if model in module_registry.get_models_for_module(module.id)
                            ]
                            context["search_scope"] = {
                                "module": module.name,
                                "model": model_key,
                            }
                            if not models:
                                context["slash_error"] = "Model not found in module."
                            else:
                                context["object_results"], truncated = _collect_object_results(
                                    request,
                                    permission_manager,
                                    models,
                                    search_value,
                                    PER_MODEL_LIMIT,
                                    TOTAL_LIMIT,
                                )
                                context["results_truncated"] = context["results_truncated"] or truncated
                    else:
                        context["slash_error"] = "Use /<module>//<query>, //<model>/<query>, or /<module>/<model>/<query>."

        case _:
            search_query = trimmed_query
            context["search_type"] = "general"
            context["search_label"] = "All content"
            context["highlight_query"] = search_query
            context["query"] = search_query

            if search_query:
                models = [
                    content_type.model_class()
                    for content_type in request.user.accessible_content_types
                ]
                context["object_results"], truncated = _collect_object_results(
                    request,
                    permission_manager,
                    models,
                    search_query,
                    PER_MODEL_LIMIT,
                    TOTAL_LIMIT,
                )
                context["results_truncated"] = context["results_truncated"] or truncated

    return render(request, "components/global_search.html", context)
    


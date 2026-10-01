from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import Count, ForeignKey, OneToOneField, Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager

from ..definition import DataviewPagination, DataviewState
from .config import KanbanDataView

if TYPE_CHECKING:
    from bloomerp.models import ApplicationField
    from bloomerp.models.users.user import AbstractBloomerpUser
    from bloomerp.models.users.user_list_view_preference import UserListViewPreference

from ..definition import BaseDataviewRenderer

KANBAN_EMPTY_COLUMN_VALUE = "__none__"
KANBAN_MAX_RELATED_COLUMNS = 50


class KanbanDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/features/dataviews/kanban.html"
    reserved_query_params = {"kanban_page", "kanban_column"}

    def get_context_data(self, pagination: DataviewPagination) -> dict[str, Any]:
        """Build paginated lanes and their configured drop targets and colours."""
        context = super().get_context_data(pagination)
        move_url = reverse(
            "components_dataview_renderer_operation",
            kwargs={
                "content_type_id": self.state.content_type_id,
                "preference_id": self.state.preference.pk,
                "action": "move",
            },
        )
        operation_querystring = self.build_page_querystring(
            self.state.request,
            self.state.operation_context_token,
        )
        if operation_querystring:
            move_url = f"{move_url}?{operation_querystring}"
        group_by_field = self.get_group_by_field(
            self.state.fields,
            self.options,
        )
        page_size = getattr(self.options, "page_size", 25)
        kanban_groups = None
        kanban_too_many_groups = False
        if group_by_field:
            model_field = self._get_model_field(
                self.state.queryset,
                group_by_field.field,
            )
            allowed_related_queryset = None
            if isinstance(model_field, (ForeignKey, OneToOneField)):
                allowed_related_queryset = self.get_allowed_related_queryset(
                    group_by_field,
                    self.state.request.user,
                )
                kanban_too_many_groups = self.has_too_many_related_columns(
                    allowed_related_queryset
                )

            if not kanban_too_many_groups:
                kanban_groups = self.build_groups(
                    self.state.queryset,
                    group_by_field,
                    user=self.state.request.user,
                    allowed_related_queryset=allowed_related_queryset,
                    preference=self.state.preference,
                    page_size=page_size,
                    options=self.options,
                )

        context.update({
            "kanban_groups": kanban_groups,
            "kanban_too_many_groups": kanban_too_many_groups,
            "group_by_field": group_by_field,
            "kanban_page_querystring": self.build_page_querystring(self.state.request),
            "component_args" : {
                "data-group-by-field-id": group_by_field.id if group_by_field else "",
                "data-group-by-field" : group_by_field.field if group_by_field else "",
                "data-kanban-move-url": move_url,
            }
        })
        return context

    @staticmethod
    def get_allowed_related_queryset(
        group_by_field: ApplicationField,
        user: AbstractBloomerpUser,
    ) -> QuerySet:
        """Return related lane values allowed by permissions and field limits."""
        model_field = group_by_field._get_model_field()
        if not isinstance(model_field, (ForeignKey, OneToOneField)):
            raise ValueError("Kanban related lanes require a foreign-key field.")

        related_model = model_field.remote_field.model
        queryset = UserPolicyManager(user).get_queryset(
            related_model,
            BloomerpPermission.VIEW,
        )
        limit_choices_to = model_field.get_limit_choices_to()
        if limit_choices_to:
            queryset = queryset.complex_filter(limit_choices_to)
        return queryset.distinct()

    @staticmethod
    def has_too_many_related_columns(related_queryset: QuerySet) -> bool:
        """Return whether the eligible foreign-key lane count exceeds the limit."""
        return related_queryset.order_by().count() > KANBAN_MAX_RELATED_COLUMNS

    @classmethod
    def build_page_querystring(
        cls,
        request,
        operation_context_token: str | None = None,
    ) -> str:
        querydict = request.GET.copy()
        for key in ("page", "kanban_page", "kanban_column"):
            querydict.pop(key, None)
        if operation_context_token:
            querydict["_dataview_operation_context"] = operation_context_token
        return querydict.urlencode()

    @classmethod
    def get_group_by_field(cls, dataview_fields, options):
        return cls.get_field_from_data_view_fields(
            dataview_fields,
            getattr(options, "group_by_field", None),
        )

    @classmethod
    def handle_action(cls, action: str, request: HttpRequest, state: DataviewState) -> HttpResponse:
        """Handle card moves and additional pages of ordinary or custom lanes."""
        if action == "move":
            return cls._move_card(request, state)
        if action != "column":
            return super().handle_action(action, request, state)

        group_by_field = cls.get_group_by_field(
            state.fields,
            state.options,
        )
        if not group_by_field:
            return HttpResponse("Kanban grouping is not configured.", status=400)

        column_value = request.GET.get("kanban_column")
        if not column_value:
            return HttpResponse("Missing kanban column.", status=400)

        groups = cls.build_groups(
            state.queryset, group_by_field, user=request.user,
            preference=state.preference,
            options=state.options,
            page_size=getattr(state.options, "page_size", 25),
            page_number=request.GET.get("kanban_page", 1),
        )
        group = next((item for item in groups if item["request_value"] == column_value), None)
        if group is None:
            return HttpResponse("Kanban column not found.", status=404)

        return render(
            request,
            "components/objects/dataview_kanban_cards.html",
            {
                "content_type_id": state.content_type.id,
                "fields": state.render_fields,
                "avatar_field": state.avatar_field,
                "group": group,
                "preference": state.preference,
                "kanban_page_querystring": cls.build_page_querystring(
                    request,
                    state.operation_context_token,
                ),
            },
        )

    @classmethod
    def _move_card(cls, request: HttpRequest, state: DataviewState) -> HttpResponse:
        """Persist a concrete lane value after existing object and field checks."""
        if request.method != "POST":
            return HttpResponse("Method not allowed", status=405)

        object_id = request.POST.get("object_id")
        group_value = request.POST.get("group_value")
        if not object_id:
            return HttpResponse("Missing required fields", status=400)

        group_by_field = cls.get_group_by_field(state.fields, state.options)
        if not group_by_field:
            return HttpResponse("Kanban grouping is not configured.", status=400)

        permission_manager = UserPolicyManager(request.user)
        if not permission_manager.has_field_permission(
            group_by_field,
            BloomerpPermission.CHANGE,
        ):
            return HttpResponse("Permission denied", status=403)

        obj = get_object_or_404(state.queryset, pk=object_id)
        if not permission_manager.has_access_to_object(
            obj,
            BloomerpPermission.CHANGE,
        ):
            return HttpResponse("Permission denied", status=403)

        model_field = state.model._meta.get_field(group_by_field.field)
        normalized_value = (
            None
            if group_value in (None, "", KANBAN_EMPTY_COLUMN_VALUE)
            else group_value
        )
        if normalized_value is None:
            if not model_field.null and not model_field.blank:
                return HttpResponse("Field does not allow empty values", status=400)
            value = "" if model_field.empty_strings_allowed and not model_field.null else None
        else:
            try:
                if isinstance(model_field, (ForeignKey, OneToOneField)):
                    value = cls.get_allowed_related_queryset(
                        group_by_field,
                        request.user,
                    ).get(pk=normalized_value)
                else:
                    value = model_field.clean(normalized_value, obj)
            except (ObjectDoesNotExist, TypeError, ValidationError, ValueError) as exc:
                return HttpResponse(f"Invalid value: {exc}", status=400)

        setattr(obj, group_by_field.field, value)
        obj.save(update_fields=[group_by_field.field])
        return JsonResponse({"status": "ok"})

    @classmethod
    def build_column_group(
        cls,
        queryset,
        group_by_field,
        column_value: str,
        preference=None,
        page_size: int | None = None,
        page_number=1,
    ) -> dict | None:
        field_name = group_by_field.field
        field_type = group_by_field.field_type
        model_field = cls._get_model_field(queryset, field_name)
        value = cls._coerce_column_value(column_value, model_field)

        column_queryset = cls._build_column_queryset(queryset, field_name, model_field, value, preference=preference)
        item_count = column_queryset.count()
        if item_count == 0 and value is not None:
            return None

        if value is None:
            label = "Unassigned"
        elif field_type in ["ForeignKey", "OneToOneField"]:
            label = cls._get_related_label(queryset, field_name, value)
        else:
            label = cls._get_choice_label(model_field, value)

        return cls._build_group(
            value,
            label,
            column_queryset,
            page_size,
            page_number,
            item_count=item_count,
        )

    @classmethod
    def build_groups(
        cls,
        queryset: QuerySet,
        group_by_field: ApplicationField,
        user: AbstractBloomerpUser | None = None,
        allowed_related_queryset: QuerySet | None = None,
        preference: UserListViewPreference | None = None,
        page_size: int | None = None,
        page_number: int | str = 1,
        options: KanbanDataView | None = None,
    ) -> list[dict[str, Any]]:
        """Build eligible lanes, merging configured members without hiding unmapped cards."""
        field_name = group_by_field.field
        model_field = cls._get_model_field(queryset, field_name)
        groups = []

        if isinstance(model_field, (ForeignKey, OneToOneField)):
            count_rows = list(
                queryset
                .values(field_name)
                .annotate(item_count=Count("pk"))
                .order_by(field_name)
            )
            counts_by_value = {
                row[field_name]: row["item_count"]
                for row in count_rows
            }

            if None in counts_by_value:
                items = cls._build_column_queryset(queryset, field_name, model_field, None, preference=preference)
                groups.append(cls._build_group(
                    None, "Unassigned", items, page_size, page_number,
                    item_count=counts_by_value[None]
                ))

            if allowed_related_queryset is None:
                allowed_related_queryset = cls.get_allowed_related_queryset(
                    group_by_field,
                    user,
                )

            for related_object in allowed_related_queryset:
                value = related_object.pk
                items = cls._build_column_queryset(
                    queryset,
                    field_name,
                    model_field,
                    value,
                    preference=preference,
                )
                groups.append(cls._build_group(
                    value,
                    str(related_object),
                    items,
                    page_size,
                    page_number,
                    item_count=counts_by_value.get(value, 0),
                ))
        else:
            empty_count = queryset.filter(cls._build_empty_filter(field_name, model_field)).count()
            if empty_count:
                items = cls._build_column_queryset(queryset, field_name, model_field, None, preference=preference)
                groups.append(cls._build_group(
                    None, "Unassigned", items, page_size, page_number,
                    item_count=empty_count
                ))

            if model_field and getattr(model_field, "choices", None):
                seen_values = set()
                counts_by_value = {
                    row[field_name]: row["item_count"]
                    for row in (
                        queryset
                        .exclude(cls._build_empty_filter(field_name, model_field))
                        .values(field_name)
                        .annotate(item_count=Count("pk"))
                        .order_by(field_name)
                    )
                }

                for choice_value, choice_label in cls._iter_choices(model_field.choices):
                    if choice_value in (None, ""):
                        continue

                    choice_items = cls._build_column_queryset(queryset, field_name, model_field, choice_value, preference=preference)
                    groups.append(cls._build_group(
                        choice_value, str(choice_label), choice_items, page_size, page_number,
                        item_count=counts_by_value.get(choice_value, 0)
                    ))
                    seen_values.add(choice_value)

                for value, item_count in counts_by_value.items():
                    if value in seen_values:
                        continue
                    items = cls._build_column_queryset(queryset, field_name, model_field, value, preference=preference)
                    groups.append(cls._build_group(
                        value, str(value), items, page_size, page_number,
                        item_count=item_count
                    ))
            else:
                count_rows = (
                    queryset
                    .exclude(cls._build_empty_filter(field_name, model_field))
                    .values(field_name)
                    .annotate(item_count=Count("pk"))
                    .order_by(field_name)
                )
                for row in count_rows:
                    value = row[field_name]
                    items = cls._build_column_queryset(queryset, field_name, model_field, value, preference=preference)
                    groups.append(cls._build_group(
                        value, str(value), items, page_size, page_number,
                        item_count=row["item_count"]
                    ))

        custom_groupings = getattr(options, "custom_groupings", {})
        colours = getattr(options, "lane_colouring", {})
        if custom_groupings:
            groups = cls._merge_custom_groups(
                groups, custom_groupings, queryset, group_by_field,
                preference, page_size, page_number,
            )
        for group in groups:
            colour_key = group.get("colour_key", group["request_value"])
            group["colour"] = colours.get(colour_key)
            group.setdefault("destinations", [{"value": group["request_value"], "label": group["label"]}])
            group["destination_value"] = group["destinations"][0]["value"]
            for destination in group["destinations"]:
                destination["colour"] = colours.get(destination["value"], group["colour"])
            for item in group["items"]:
                raw_value = getattr(item, model_field.attname) if model_field else getattr(item, field_name)
                item.kanban_header_colour = colours.get(cls._format_column_value(raw_value), group["colour"])
                item.kanban_header_foreground = cls._header_foreground(item.kanban_header_colour)
        return groups

    @staticmethod
    def _header_foreground(colour: str | None) -> str:
        """Choose the higher-contrast black or white text for a configured header."""
        if not colour:
            return "#111827"
        channels = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        luminance = sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))
        return "#000000" if luminance > 0.179 else "#ffffff"

    @classmethod
    def _merge_custom_groups(
        cls,
        groups: list[dict[str, Any]],
        custom_groupings: dict[str, list[str]],
        queryset: QuerySet,
        group_by_field: ApplicationField,
        preference: UserListViewPreference | None,
        page_size: int | None,
        page_number: int | str,
    ) -> list[dict[str, Any]]:
        """Combine eligible member querysets before pagination and retain original lanes."""
        by_value = {group["request_value"]: group for group in groups}
        consumed: set[str] = set()
        merged: list[dict[str, Any]] = []
        model_field = cls._get_model_field(queryset, group_by_field.field)
        for label, values in custom_groupings.items():
            members = [by_value[value] for value in values if value in by_value and value not in consumed]
            if not members:
                continue
            lane_filter = Q(pk__in=[])
            for member in members:
                consumed.add(member["request_value"])
                if member["value"] is None:
                    lane_filter |= cls._build_empty_filter(group_by_field.field, model_field)
                else:
                    lane_filter |= Q(**{group_by_field.field: member["value"]})
            items = queryset.filter(lane_filter)
            sort_options = (preference.options or {}).get("kanban", {}) if preference else {}
            sort_field = sort_options.get("sort_field")
            if sort_field:
                items = items.order_by(("-" if sort_options.get("sort_direction") == "desc" else "") + sort_field)
            group = cls._build_group(
                label, label, items, page_size, page_number,
                item_count=sum(member["count"] for member in members),
            )
            group.update({
                "request_value": "__group__:" + label,
                "colour_key": label,
                "destinations": [{"value": member["request_value"], "label": member["label"]} for member in members],
            })
            merged.append(group)
        merged.extend(group for group in groups if group["request_value"] not in consumed)
        return merged


    @staticmethod
    def _format_column_value(value) -> str:
        return KANBAN_EMPTY_COLUMN_VALUE if value in (None, "") else str(value)

    @staticmethod
    def _get_model_field(queryset, field_name: str):
        model = queryset.model
        if not hasattr(model, "_meta"):
            return None

        try:
            return model._meta.get_field(field_name)
        except Exception:
            return None

    @staticmethod
    def _iter_choices(choices):
        for choice_value, choice_label in choices:
            if isinstance(choice_label, (list, tuple)):
                for nested_value, nested_label in choice_label:
                    yield nested_value, nested_label
            else:
                yield choice_value, choice_label

    @classmethod
    def _field_allows_blank_string(cls, model_field) -> bool:
        return bool(
            model_field
            and getattr(model_field, "empty_strings_allowed", False)
            and not (getattr(model_field, "many_to_one", False) or getattr(model_field, "one_to_one", False))
        )

    @classmethod
    def _build_empty_filter(cls, field_name: str, model_field) -> Q:
        empty_filter = Q(**{f"{field_name}__isnull": True})
        if cls._field_allows_blank_string(model_field):
            empty_filter |= Q(**{field_name: ""})
        return empty_filter

    @classmethod
    def _coerce_column_value(cls, raw_value: str, model_field):
        if raw_value == KANBAN_EMPTY_COLUMN_VALUE:
            return None

        if model_field is None:
            return raw_value

        try:
            if getattr(model_field, "many_to_one", False) or getattr(model_field, "one_to_one", False):
                return model_field.target_field.to_python(raw_value)
            return model_field.to_python(raw_value)
        except Exception:
            return raw_value

    @classmethod
    def _get_choice_label(cls, model_field, value) -> str:
        if model_field and getattr(model_field, "choices", None):
            for choice_value, choice_label in cls._iter_choices(model_field.choices):
                if choice_value == value:
                    return str(choice_label)

        return str(value)

    @staticmethod
    def _get_related_label(queryset, field_name: str, value) -> str:
        related_obj = (
            queryset
            .filter(**{field_name: value})
            .select_related(field_name)
            .first()
        )
        if related_obj:
            related_value = getattr(related_obj, field_name, None)
            if related_value:
                return str(related_value)

        return f"ID: {value}"

    @classmethod
    def _build_column_queryset(cls, queryset, field_name: str, model_field, value, preference:UserListViewPreference=None):
        sort_field = (preference.options if preference else {}).get("kanban", {}).get("sort_field", None)
        sort_direction = (preference.options if preference else {}).get("kanban", {}).get("sort_direction", "asc")
        
        if value is None:
            queryset = queryset.filter(cls._build_empty_filter(field_name, model_field))
        else:
            queryset = queryset.filter(**{field_name: value})
        
        if sort_field:
            if sort_direction == "desc":
                sort_field = f"-{sort_field}"
            queryset = queryset.order_by(sort_field)
            print(f"Sorting kanban column by {sort_field}")
        
        return queryset

    @classmethod
    def _build_group(
        cls,
        value,
        label: str,
        items: list,
        page_size: int | None = None,
        page_number=1,
        item_count: int | None = None,
    ) -> dict:
        total_count = item_count if item_count is not None else len(items)

        if page_size:
            page_obj = cls.paginate_object_list(items, page_size, page_number)
            visible_items = page_obj.object_list
        else:
            page_obj = None
            visible_items = items

        return {
            "value": value,
            "request_value": cls._format_column_value(value),
            "label": label,
            "items": visible_items,
            "count": total_count,
            "page_obj": page_obj,
            "has_next_page": page_obj.has_next() if page_obj else False,
            "next_page_number": page_obj.next_page_number() if page_obj and page_obj.has_next() else None,
        }

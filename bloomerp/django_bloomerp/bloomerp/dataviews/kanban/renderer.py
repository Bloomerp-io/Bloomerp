from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist, ValidationError
from django.db.models import Count, ForeignKey, Model, OneToOneField, Q, QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
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
    reserved_query_params = {"kanban_page", "kanban_column", "kanban_loaded_ids"}

    @classmethod
    def action_requires_count(cls, action: str) -> bool:
        """Skip the board total when saving and rendering a single moved card."""
        return action != "move"

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
            "kanban_page_querystring": self.build_page_querystring(
                self.state.request, self.state.operation_context_token
            ),
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
        request: HttpRequest,
        operation_context_token: str | None = None,
    ) -> str:
        """Keep filters and operation authorization without lane pagination parameters."""
        querydict = request.GET.copy()
        for key in {"page"} | cls.reserved_query_params:
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

        from bloomerp.components.objects.dataviews.dataview import _get_actions

        group_by_field = cls.get_group_by_field(
            state.fields,
            state.options,
        )
        if not group_by_field:
            return HttpResponse("Kanban grouping is not configured.", status=400)

        column_value = request.GET.get("kanban_column")
        if not column_value:
            return HttpResponse("Missing kanban column.", status=400)

        loaded_ids = None
        pagination_data = request.POST if request.method == "POST" else request.GET
        if "kanban_loaded_ids" in pagination_data:
            try:
                loaded_ids = cls._parse_card_ids(state.model, pagination_data["kanban_loaded_ids"])
            except (TypeError, ValueError, ValidationError):
                return HttpResponse("Invalid loaded card IDs.", status=400)

        group = cls.build_column_group(
            state.queryset, group_by_field, column_value,
            preference=state.preference,
            options=state.options,
            user=request.user,
            page_size=getattr(state.options, "page_size", 25),
            page_number=request.GET.get("kanban_page", 1),
            loaded_ids=loaded_ids,
        )
        if group is None:
            return HttpResponse("Kanban column not found.", status=404)

        card_order = None
        if loaded_ids is not None:
            card_order = cls._loaded_card_order(
                state.queryset, group_by_field, group["member_values"],
                state.preference, [*loaded_ids, *(obj.pk for obj in group["items"])],
            )
        return render(
            request,
            "components/objects/dataview_kanban_cards.html",
            {
                "content_type_id": state.content_type.id,
                "fields": state.render_fields,
                "avatar_field": state.avatar_field,
                "group": group,
                "preference": state.preference,
                "object_actions": _get_actions(state.model),
                "kanban_append": True,
                "kanban_card_order": card_order,
                "kanban_page_querystring": cls.build_page_querystring(
                    request,
                    state.operation_context_token,
                ),
            },
        )

    @staticmethod
    def _parse_card_ids(model: type[Model], raw_ids: str) -> list[Any]:
        """Validate displayed-card exclusions using the model's primary-key field."""
        return [model._meta.pk.to_python(value) for value in raw_ids.split(",") if value]

    @classmethod
    def _loaded_card_order(
        cls,
        queryset: QuerySet,
        group_by_field: ApplicationField,
        values: list[Any],
        preference: UserListViewPreference | None,
        loaded_ids: list[Any],
    ) -> list[str]:
        """Fetch loaded IDs for a configured sort, without rendering or loading a lane."""
        sort_options = (preference.options or {}).get("kanban", {}) if preference else {}
        if not sort_options.get("sort_field") or not loaded_ids:
            return []
        items = cls._lane_queryset(
            queryset, group_by_field, values, preference
        ).filter(pk__in=loaded_ids)
        return [str(pk) for pk in items.values_list("pk", flat=True)]

    @classmethod
    def _move_card(cls, request: HttpRequest, state: DataviewState) -> HttpResponse:
        """Save an authorized category and return its card and loaded destination order."""
        if request.method != "POST":
            return HttpResponse("Method not allowed", status=405)

        object_id = request.POST.get("object_id")
        group_value = request.POST.get("group_value")
        if not object_id:
            return HttpResponse("Missing required fields", status=400)

        loaded_ids = None
        if "kanban_loaded_ids" in request.POST:
            try:
                loaded_ids = cls._parse_card_ids(state.model, request.POST["kanban_loaded_ids"])
            except (TypeError, ValueError, ValidationError):
                return HttpResponse("Invalid loaded card IDs.", status=400)

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
        # Re-evaluate filters and row-sensitive field annotations after the move.
        visible_object = state.queryset.filter(pk=obj.pk).first()
        card_html = ""
        if visible_object is not None:
            from bloomerp.components.objects.dataviews.dataview import _get_actions
            from bloomerp.field_types.utils.value_loading import prepare_field_values

            cls._prepare_card_colour(visible_object, group_by_field, state.options)
            prepare_field_values([visible_object], state.render_fields)
            card_html = render_to_string(
                "components/objects/kanban_card.html",
                {
                    "object": visible_object,
                    "content_type_id": state.content_type_id,
                    "fields": state.render_fields,
                    "avatar_field": state.avatar_field,
                    "preference": state.preference,
                    "object_actions": _get_actions(state.model),
                    "row_index": request.POST.get("row_index", "0"),
                },
                request=request,
            )
        result: dict[str, Any] = {"status": "ok", "card_html": card_html}
        if loaded_ids is not None:
            concrete_value = getattr(obj, model_field.attname)
            values = [concrete_value]
            for members in getattr(state.options, "custom_groupings", {}).values():
                if cls._format_column_value(concrete_value) in members:
                    value_field = (
                        model_field.target_field
                        if isinstance(model_field, (ForeignKey, OneToOneField))
                        else model_field
                    )
                    for value in members:
                        try:
                            values.append(
                                None if value == KANBAN_EMPTY_COLUMN_VALUE
                                else value_field.to_python(value)
                            )
                        except (TypeError, ValueError, ValidationError):
                            continue
                    break
            result["ordered_ids"] = cls._loaded_card_order(
                state.queryset, group_by_field, values, state.preference,
                [*loaded_ids, obj.pk],
            )
        return JsonResponse(result)

    @classmethod
    def build_column_group(
        cls,
        queryset: QuerySet,
        group_by_field: ApplicationField,
        column_value: str,
        preference: UserListViewPreference | None = None,
        page_size: int | None = None,
        page_number: int | str = 1,
        options: KanbanDataView | None = None,
        user: AbstractBloomerpUser | None = None,
        loaded_ids: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        """Resolve and paginate only the requested ordinary or custom lane."""
        custom_groupings = getattr(options, "custom_groupings", {})
        if (
            column_value.startswith("__group__:")
            and column_value[len("__group__:") :] in custom_groupings
        ):
            requested_keys = custom_groupings.get(column_value[len("__group__:") :], [])
        else:
            requested_keys = [column_value]
        if not requested_keys:
            return None
        model_field = cls._get_model_field(queryset, group_by_field.field)
        values = []
        for key in requested_keys:
            try:
                if key == KANBAN_EMPTY_COLUMN_VALUE:
                    value = None
                elif isinstance(model_field, (ForeignKey, OneToOneField)):
                    value = model_field.target_field.to_python(key)
                else:
                    value = model_field.to_python(key) if model_field else key
            except (TypeError, ValueError, ValidationError):
                continue
            values.append(value)
        if not values:
            return None
        lane_queryset = cls._lane_queryset(queryset, group_by_field, values, preference)
        related_queryset = None
        if isinstance(model_field, (ForeignKey, OneToOneField)):
            related_queryset = cls.get_allowed_related_queryset(
                group_by_field, user
            ).filter(pk__in=[value for value in values if value is not None])
        metadata = cls.build_lane_metadata(
            lane_queryset,
            group_by_field,
            user,
            related_queryset,
        )
        metadata = cls.merge_lane_metadata(
            metadata, custom_groupings, getattr(options, "custom_group_order", []),
            getattr(options, "show_unmapped_lanes", True),
        )
        group = next(
            (item for item in metadata if item["request_value"] == column_value), None
        )
        if group is None:
            return None
        return cls._materialize_lane(
            queryset, group_by_field, group, preference, page_size,
            1 if loaded_ids is not None else page_number, options,
            loaded_ids=loaded_ids,
        )

    @classmethod
    def build_lane_metadata(
        cls,
        queryset: QuerySet,
        group_by_field: ApplicationField,
        user: AbstractBloomerpUser | None = None,
        allowed_related_queryset: QuerySet | None = None,
    ) -> list[dict[str, Any]]:
        """Collect eligible lane labels, keys and counts without querying any card objects."""
        field_name = group_by_field.field
        model_field = cls._get_model_field(queryset, field_name)
        counts = {
            row[field_name]: row["item_count"]
            for row in queryset.order_by()
            .values(field_name)
            .annotate(item_count=Count("pk"))
            .order_by(field_name)
        }
        empty_count = sum(
            count for value, count in counts.items() if value in (None, "")
        )
        groups = (
            [cls._lane_metadata(None, "Unassigned", empty_count)] if empty_count else []
        )
        if isinstance(model_field, (ForeignKey, OneToOneField)):
            related_queryset = allowed_related_queryset
            if related_queryset is None:
                related_queryset = cls.get_allowed_related_queryset(
                    group_by_field, user
                )
            groups.extend(
                cls._lane_metadata(item.pk, str(item), counts.get(item.pk, 0))
                for item in related_queryset
            )
            return groups
        seen_values = {None, ""}
        for value, label in cls._iter_choices(
            getattr(model_field, "choices", None) or []
        ):
            if value in seen_values:
                continue
            groups.append(cls._lane_metadata(value, str(label), counts.get(value, 0)))
            seen_values.add(value)
        groups.extend(
            cls._lane_metadata(value, str(value), count)
            for value, count in counts.items()
            if value not in seen_values
        )
        return groups

    @classmethod
    def _lane_metadata(cls, value: Any, label: str, count: int) -> dict[str, Any]:
        """Describe an ordinary lane without constructing or evaluating its card queryset."""
        return {
            "value": value,
            "request_value": cls._format_column_value(value),
            "label": label,
            "count": count,
            "member_values": [value],
        }

    @classmethod
    def merge_lane_metadata(
        cls,
        groups: list[dict[str, Any]],
        custom_groupings: dict[str, list[str]],
        custom_group_order: list[str] | None = None,
        show_unmapped_lanes: bool = True,
    ) -> list[dict[str, Any]]:
        """Merge eligible members and optionally retain unmapped lanes without loading cards."""
        by_value = {group["request_value"]: group for group in groups}
        consumed: set[str] = set()
        merged = []
        labels = dict.fromkeys([*(custom_group_order or []), *custom_groupings])
        for label in labels:
            values = custom_groupings.get(label, [])
            members = [
                by_value[value]
                for value in values
                if value in by_value and value not in consumed
            ]
            if not members:
                continue
            consumed.update(member["request_value"] for member in members)
            merged.append(
                {
                    "value": label,
                    "label": label,
                    "request_value": "__group__:" + label,
                    "colour_key": label,
                    "count": sum(member["count"] for member in members),
                    "member_values": [
                        value for member in members for value in member["member_values"]
                    ],
                    "destinations": [
                        {"value": member["request_value"], "label": member["label"]}
                        for member in members
                    ],
                }
            )
        if show_unmapped_lanes:
            merged.extend(
                group for group in groups if group["request_value"] not in consumed
            )
        return merged

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
        """Resolve lane metadata first, then load only each final lane's visible page."""
        metadata = cls.build_lane_metadata(
            queryset, group_by_field, user, allowed_related_queryset
        )
        metadata = cls.merge_lane_metadata(
            metadata, getattr(options, "custom_groupings", {}),
            getattr(options, "custom_group_order", []),
            getattr(options, "show_unmapped_lanes", True),
        )
        return [
            cls._materialize_lane(
                queryset,
                group_by_field,
                group,
                preference,
                page_size,
                page_number,
                options,
            )
            for group in metadata
        ]

    @classmethod
    def _lane_queryset(
        cls,
        queryset: QuerySet,
        group_by_field: ApplicationField,
        values: list[Any],
        preference: UserListViewPreference | None,
    ) -> QuerySet:
        """Filter lane members and apply saved sorting with a stable primary-key tie break."""
        model_field = cls._get_model_field(queryset, group_by_field.field)
        lane_filter = Q(pk__in=[])
        for value in values:
            lane_filter |= (
                cls._build_empty_filter(group_by_field.field, model_field)
                if value is None
                else Q(**{group_by_field.field: value})
            )
        items = queryset.filter(lane_filter)
        sort_options = (
            (preference.options or {}).get("kanban", {}) if preference else {}
        )
        sort_field = sort_options.get("sort_field")
        if sort_field:
            items = items.order_by(
                ("-" if sort_options.get("sort_direction") == "desc" else "")
                + sort_field,
                "pk",
            )
        return items

    @classmethod
    def _materialize_lane(
        cls,
        queryset: QuerySet,
        group_by_field: ApplicationField,
        metadata: dict[str, Any],
        preference: UserListViewPreference | None,
        page_size: int | None,
        page_number: int | str,
        options: KanbanDataView | None,
        loaded_ids: list[Any] | None = None,
    ) -> dict[str, Any]:
        """Paginate one final lane and attach its header and destination presentation."""
        items = cls._lane_queryset(
            queryset, group_by_field, metadata["member_values"], preference
        )
        if loaded_ids is not None:
            items = items.exclude(pk__in=loaded_ids)
        group = cls._build_group(
            metadata["value"],
            metadata["label"],
            items,
            page_size,
            page_number,
            metadata["count"],
        )
        group.update(metadata)
        colours = getattr(options, "lane_colouring", {})
        group["colour"] = colours.get(group.get("colour_key", group["request_value"]))
        group["foreground"] = cls._header_foreground(group["colour"])
        group.setdefault(
            "destinations", [{"value": group["request_value"], "label": group["label"]}]
        )
        group["destination_value"] = group["destinations"][0]["value"]
        for destination in group["destinations"]:
            destination["colour"] = colours.get(destination["value"], group["colour"])
        for item in group["items"]:
            cls._prepare_card_colour(item, group_by_field, options)
        return group

    @classmethod
    def _prepare_card_colour(
        cls,
        obj: Any,
        group_by_field: ApplicationField,
        options: KanbanDataView | None,
    ) -> None:
        """Apply the same concrete-category and custom-lane colours to every card render."""
        try:
            model_field = obj._meta.get_field(group_by_field.field)
            attribute = model_field.attname
        except FieldDoesNotExist:
            attribute = group_by_field.field
        value = cls._format_column_value(getattr(obj, attribute))
        custom_groups = getattr(options, "custom_groupings", {})
        lane_key = next(
            (name for name, values in custom_groups.items() if value in values), value
        )
        colours = getattr(options, "lane_colouring", {})
        obj.kanban_header_colour = colours.get(value, colours.get(lane_key))
        obj.kanban_header_foreground = cls._header_foreground(obj.kanban_header_colour)

    @staticmethod
    def _header_foreground(colour: str | None) -> str:
        """Choose the higher-contrast black or white text for a configured header."""
        if not colour:
            return "#111827"
        channels = [int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
        luminance = sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))
        return "#000000" if luminance > 0.179 else "#ffffff"

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

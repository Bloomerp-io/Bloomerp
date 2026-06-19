from __future__ import annotations

from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import render

from .base import BaseDataviewRenderer


KANBAN_EMPTY_COLUMN_VALUE = "__none__"


class KanbanDataviewRenderer(BaseDataviewRenderer):
    template_name = "cotton/ui/data_view/kanban.html"
    reserved_query_params = {"kanban_page", "kanban_column"}

    def get_context_data(self, pagination) -> dict:
        context = super().get_context_data(pagination)
        group_by_field = self.get_group_by_field(
            self.state.fields,
            self.options,
        )
        page_size = getattr(self.options, "page_size", 25)
        kanban_groups = None
        if group_by_field:
            kanban_groups = self.build_groups(
                self.state.queryset,
                group_by_field,
                page_size=page_size,
            )

        context.update({
            "kanban_groups": kanban_groups,
            "group_by_field": group_by_field,
            "kanban_page_querystring": self.build_page_querystring(self.state.request),
            "component_args" : {
                "data-group-by-field-id": getattr(self.options, "group_by_field_id", ""),
                "data-group-by-field" : group_by_field.field if group_by_field else "",
            }
        })
        return context

    @classmethod
    def build_page_querystring(cls, request) -> str:
        return cls.build_querystring(request, ("page", "kanban_page", "kanban_column"))

    @classmethod
    def get_group_by_field(cls, data_view_fields, options):
        return cls.get_field_from_data_view_fields(
            data_view_fields,
            getattr(options, "group_by_field_id", None),
        )

    @classmethod
    def handle_action(cls, action: str, request, state) -> HttpResponse:
        if action != "column":
            return super().handle_action(action, request, state)

        group_by_field = cls.get_group_by_field(
            state.data_view_fields,
            state.dataview_options,
        )
        if not group_by_field:
            return HttpResponse("Kanban grouping is not configured.", status=400)

        column_value = request.GET.get("kanban_column")
        if not column_value:
            return HttpResponse("Missing kanban column.", status=400)

        group = cls.build_column_group(
            state.queryset,
            group_by_field,
            column_value,
            page_size=getattr(state.dataview_options, "page_size", 25),
            page_number=request.GET.get("kanban_page", 1),
        )
        if group is None:
            return HttpResponse("Kanban column not found.", status=404)

        return render(
            request,
            "components/objects/dataview_kanban_cards.html",
            {
                "content_type_id": state.content_type.id,
                "fields": state.data_view_render_fields,
                "avatar_field": state.avatar_field,
                "group": group,
                "kanban_page_querystring": cls.build_page_querystring(request),
            },
        )

    @classmethod
    def build_column_group(
        cls,
        queryset,
        group_by_field,
        column_value: str,
        page_size: int | None = None,
        page_number=1,
    ) -> dict | None:
        field_name = group_by_field.field
        field_type = group_by_field.field_type
        model_field = cls._get_model_field(queryset, field_name)
        value = cls._coerce_column_value(column_value, model_field)

        column_queryset = cls._build_column_queryset(queryset, field_name, model_field, value)
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
    def build_groups(cls, queryset, group_by_field, page_size: int | None = None, page_number=1) -> list[dict]:
        field_name = group_by_field.field
        field_type = group_by_field.field_type
        model_field = cls._get_model_field(queryset, field_name)
        groups = []

        if field_type in ["ForeignKey", "OneToOneField"]:
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
                items = cls._build_column_queryset(queryset, field_name, model_field, None)
                groups.append(cls._build_group(
                    None, "Unassigned", items, page_size, page_number,
                    item_count=counts_by_value[None]
                ))

            related_labels = {}
            if model_field and getattr(model_field, "remote_field", None):
                related_model = model_field.remote_field.model
                related_values = [value for value in counts_by_value if value is not None]
                related_labels = {
                    pk: str(related_obj)
                    for pk, related_obj in related_model.objects.in_bulk(related_values).items()
                }

            for row in count_rows:
                value = row[field_name]
                if value is not None:
                    items = cls._build_column_queryset(queryset, field_name, model_field, value)
                    label = related_labels.get(value, f"ID: {value}")
                    groups.append(cls._build_group(
                        value, label, items, page_size, page_number,
                        item_count=row["item_count"]
                    ))
        else:
            empty_count = queryset.filter(cls._build_empty_filter(field_name, model_field)).count()
            if empty_count:
                items = cls._build_column_queryset(queryset, field_name, model_field, None)
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

                    choice_items = cls._build_column_queryset(queryset, field_name, model_field, choice_value)
                    groups.append(cls._build_group(
                        choice_value, str(choice_label), choice_items, page_size, page_number,
                        item_count=counts_by_value.get(choice_value, 0)
                    ))
                    seen_values.add(choice_value)

                for value, item_count in counts_by_value.items():
                    if value in seen_values:
                        continue
                    items = cls._build_column_queryset(queryset, field_name, model_field, value)
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
                    items = cls._build_column_queryset(queryset, field_name, model_field, value)
                    groups.append(cls._build_group(
                        value, str(value), items, page_size, page_number,
                        item_count=row["item_count"]
                    ))

        return groups

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
    def _build_column_queryset(cls, queryset, field_name: str, model_field, value):
        if value is None:
            return queryset.filter(cls._build_empty_filter(field_name, model_field))
        return queryset.filter(**{field_name: value})

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

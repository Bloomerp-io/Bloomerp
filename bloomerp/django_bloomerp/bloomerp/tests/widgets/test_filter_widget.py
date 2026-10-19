import json
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.template.loader import render_to_string
from django.test import RequestFactory
from django.urls import reverse

from bloomerp.widgets.filter_widget import FilterWidget
from bloomerp.tests.base import (
    BloomerpWidgetTestCase,
    WidgetScenario,
    WidgetOperation,
)


class TestFilterWidget(BloomerpWidgetTestCase):
    widget_class = FilterWidget

    def get_test_scenarios(self) -> list[WidgetScenario[FilterWidget]]:
        """Cover filter serialization and rendering with optional request capabilities."""
        model = get_user_model()
        content_type = ContentType(pk=42)
        filters = [
            {
                "connector": "AND",
                "conditions": [
                    {"field_path": "email", "lookup_id": "exact", "value": "a@b.test"},
                ],
            },
        ]
        filters_json = json.dumps(filters)

        return [
            WidgetScenario(
                name="policy builder renders filter endpoints without a request",
                constructor_kwargs={"content_type": content_type, "include_controls": False},
                operations=[WidgetOperation(
                    name="render policy row filter",
                    execute=self.render_policy_filter,
                    result_validators=self.has_plain_filter_endpoints,
                )],
            ),
            WidgetScenario(
                name="request-aware filters retain their permission token",
                constructor_kwargs={"content_type": content_type},
                operations=[WidgetOperation(
                    name="render with request capability",
                    execute=self.render_with_request,
                    result_validators=self.has_token_filter_endpoints,
                )],
            ),
            WidgetScenario(
                name="outer controls default to enabled",
                constructor_args=(content_type,),
                operations=[WidgetOperation(name="render controls", execute=lambda widget: widget.render("filters", []),
                    result_validators=lambda html: 'data-include-controls="true"' in html)],
            ),
            WidgetScenario(
                name="outer controls can be disabled",
                constructor_args=(content_type,),
                constructor_kwargs={"include_controls": False},
                operations=[WidgetOperation(name="render no controls", execute=lambda widget: widget.render("filters", []),
                    result_validators=lambda html: 'data-include-controls="false"' in html)],
            ),
            WidgetScenario(
                name="model initialization derives model scope identifier",
                constructor_kwargs={"model": model},
                constructor_validators=lambda widget: widget.model is model,
                operations=[
                    WidgetOperation(
                        name="content type id",
                        execute=lambda widget: self._model_content_type_id(widget, 17),
                        result_validators=lambda value: value == 17,
                    ),
                ],
            ),
            WidgetScenario(
                name="content type initialization",
                constructor_args=(content_type,),
                constructor_validators=lambda widget: widget.content_type is content_type,
                operations=[
                    WidgetOperation(
                        name="render scope metadata",
                        execute=lambda widget: widget.render(
                            "filters",
                            filters_json,
                            attrs={"id": "id_filters", "required": True, "disabled": True},
                        ),
                        result_validators=lambda html: (
                            'data-scope="model"' in html
                            and 'data-scope-id="42"' in html
                            and 'data-name="filters"' in html
                            and 'id="id_filters"' in html
                            and 'required' in html
                            and 'disabled' in html
                        ),
                    ),
                ],
            ),
            WidgetScenario(
                name="empty values become an empty filter list",
                constructor_args=(content_type,),
                operations=[
                    WidgetOperation(
                        name="format empty value",
                        execute=lambda widget: widget.format_value(None),
                        result_validators=lambda value: value == "[]",
                    ),
                ],
            ),
            WidgetScenario(
                name="valid JSON round trip",
                constructor_args=(content_type,),
                operations=[
                    WidgetOperation(
                        name="format JSON",
                        execute=lambda widget: widget.format_value(filters_json),
                        result_validators=lambda value: json.loads(value) == filters,
                    ),
                    WidgetOperation(
                        name="extract submitted JSON",
                        execute=lambda widget: widget.value_from_datadict(
                            {"filters": filters_json}, {}, "filters"
                        ),
                        result_validators=lambda value: json.loads(value) == filters,
                    ),
                ],
            ),
            WidgetScenario(
                name="invalid JSON is safely escaped for visible frontend error",
                constructor_args=(content_type,),
                operations=[
                    WidgetOperation(
                        name="render invalid JSON",
                        execute=lambda widget: widget.render(
                            "filters",
                            'not-json\"><script>alert(1)</script>',
                        ),
                        result_validators=lambda html: (
                            'data-initial-filters="not-json&quot;' in html
                            and "<script>alert(1)</script>" not in html
                        ),
                    ),
                ],
            ),
        ]

    def render_policy_filter(self, widget: FilterWidget) -> str:
        """Render the row-policy editor through the request-free Django widget renderer."""
        return widget.render("row_policy_filter", [], attrs={"data-max-groups": "1"})

    def render_with_request(self, widget: FilterWidget) -> str:
        """Render a filter in a request context carrying an existing capability."""
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        context = widget.get_context("filters", [], {})
        context["request"] = request
        with patch("bloomerp.permissions.access_tokens.request_permission_token", return_value="test-capability"):
            return render_to_string(widget.template_name, context)

    def has_plain_filter_endpoints(self, html: str) -> bool:
        """Verify all editor endpoints remain usable without a request capability."""
        return self.has_filter_endpoints(html, "")

    def has_token_filter_endpoints(self, html: str) -> bool:
        """Verify each editor endpoint propagates the request's capability."""
        return self.has_filter_endpoints(html, "?_permission_token=test-capability")

    def has_filter_endpoints(self, html: str, suffix: str) -> bool:
        """Check all five filter URLs in the rendered component markup."""
        container = BeautifulSoup(html, "html.parser").select_one('[bloomerp-component="unified-filter-container"]')
        endpoints = {
            "data-fields-url": "components_filters_fields",
            "data-lookups-url": "components_filters_lookups",
            "data-value-editor-url": "components_filters_value_editor",
            "data-presets-url": "components_filters_get",
            "data-save-preset-url": "components_filters_save",
        }
        return container is not None and all(
            container.get(attribute) == reverse(route) + suffix
            for attribute, route in endpoints.items()
        )

    @staticmethod
    def _model_content_type_id(widget, pk):
        with patch.object(ContentType.objects, "get_for_model", return_value=ContentType(pk=pk)):
            return widget.content_type_id

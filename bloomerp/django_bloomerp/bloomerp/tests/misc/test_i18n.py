from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from babel.messages.catalog import Catalog, Message
from django.apps import apps
from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils.functional import Promise
from django.utils.translation import override

from bloomerp.config.definition import (
    BloomerpAppI18nSettings,
    BloomerpConfig,
    BloomerpI18nSettings,
)
from bloomerp.i18n.apps import discover_translatable_apps, get_app_source_language
from bloomerp.i18n.catalogs import (
    approve_translated_messages,
    merge_messages,
    read_catalog,
    reconcile_obsolete_messages,
    save_catalog,
    validate_message,
)
from bloomerp.i18n.models import model_messages
from bloomerp.i18n.modules import module_messages
from bloomerp.i18n.languages import catalog_locale, normalize_language_code
from bloomerp.i18n.routes import route_messages
from bloomerp.i18n.translator import TranslationBatch, TranslationResult, translate_catalog
from bloomerp.management.commands.bloomerp_i18n import Command as I18nCommand
from bloomerp.models.audit.activity_log import ActivityLog, ActivityLogAction, ActivityLogSource
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.todo import Todo, TodoStatus
from bloomerp.models.workspaces.workspace import Workspace
from bloomerp.modules.definition import ModuleConfig
from bloomerp.router import (
    BloomerpRoute,
    BloomerpRouteRegistry,
    RouteType,
    ViewType,
    _auto_generate_url_name,
)
from bloomerp.services.sectioned_layout_services import resolve_detail_layout_rows
from bloomerp.utils.models import get_create_view_url, model_name_plural_slug


class TestI18nConfiguration(SimpleTestCase):
    def test_i18n_configuration_is_nested_on_bloomerp_config(self):
        config = BloomerpConfig(
            i18n={
                "languages": ["nl", "de"],
                "apps": ["bloomerp"],
                "llm": {"model": "example-model", "provider": "example"},
            }
        )

        self.assertEqual(config.i18n.languages, ["nl", "de"])
        self.assertEqual(config.i18n.apps, ["bloomerp"])
        self.assertEqual(config.i18n.llm.provider, "example")

    def test_explicit_app_discovery_accepts_app_label(self):
        discovered = discover_translatable_apps(
            BloomerpI18nSettings(apps=["bloomerp"])
        )

        self.assertEqual([app.label for app in discovered], ["bloomerp"])

    def test_auto_discovery_excludes_apps_installed_inside_project_venv(self):
        discovered = discover_translatable_apps(BloomerpI18nSettings())
        labels = {app.label for app in discovered}

        self.assertIn("bloomerp", labels)
        self.assertNotIn("channels", labels)
        self.assertNotIn("auth", labels)

    def test_app_source_language_prefers_project_override_then_app_metadata(self):
        app = SimpleNamespace(
            label="vendas",
            name="empresa.vendas",
            bloomerp_i18n=BloomerpAppI18nSettings(source_language="pt_BR"),
        )

        self.assertEqual(
            get_app_source_language(app, BloomerpI18nSettings()),
            "pt-br",
        )
        self.assertEqual(
            get_app_source_language(
                app,
                BloomerpI18nSettings(app_source_languages={"vendas": "pt-PT"}),
            ),
            "pt-pt",
        )

    def test_model_route_identity_uses_app_source_language(self):
        with override("nl"):
            self.assertEqual(str(Workspace._meta.verbose_name_plural), "Werkruimten")
            self.assertEqual(model_name_plural_slug(Workspace), "workspaces")
            self.assertEqual(get_create_view_url(Workspace), "workspaces_add")
            self.assertEqual(
                _auto_generate_url_name("add", RouteType.MODEL, Workspace),
                "workspaces_add",
            )
            self.assertEqual(
                reverse(get_create_view_url(Workspace)),
                "/misc/workspaces/create/",
            )

    def test_command_calculates_translation_targets_per_app(self):
        english_app = SimpleNamespace(
            label="bloomerp",
            name="bloomerp",
            bloomerp_i18n=BloomerpAppI18nSettings(source_language="en-us"),
        )
        portuguese_app = SimpleNamespace(
            label="vendas",
            name="empresa.vendas",
            bloomerp_i18n=BloomerpAppI18nSettings(source_language="pt"),
        )
        config = BloomerpI18nSettings(languages=["en-us", "pt", "de"])
        command = I18nCommand()

        resolved = command._app_languages(
            [english_app, portuguese_app],
            command._languages(config.languages, None),
            config,
        )

        self.assertEqual(resolved[0][1:], ("en-us", ["pt", "de"]))
        self.assertEqual(resolved[1][1:], ("pt", ["en_US", "de"]))

    def test_regional_language_codes_have_runtime_and_catalog_forms(self):
        self.assertEqual(normalize_language_code("pt_BR"), "pt-br")
        self.assertEqual(catalog_locale("pt-br"), "pt_BR")

    def test_route_localization_translates_template_before_model_formatting(self):
        model = SimpleNamespace(_meta=SimpleNamespace(verbose_name="Cliente"))
        route = BloomerpRoute(
            path="/clientes/",
            route_type=RouteType.MODEL,
            name="Cliente List",
            url_name="clientes_model",
            view_type=ViewType.FUNCTION,
            view=lambda request: None,
            model=model,
            name_message="{model} list",
            owner_app_label="vendas",
        )

        with patch(
            "bloomerp.router.pgettext",
            side_effect=lambda context, message: (
                "Lista de {model}" if message == "{model} list" else message
            ),
        ):
            self.assertEqual(route.localized_name, "Lista de Cliente")

    def test_route_localization_formats_related_model_metadata_at_runtime(self):
        model = SimpleNamespace(_meta=SimpleNamespace(verbose_name="Account"))
        route = BloomerpRoute(
            path="accounts/<int:pk>/contacts/",
            route_type=RouteType.DETAIL,
            name="Contacts",
            url_name="accounts_contacts_relationship",
            view_type=ViewType.FUNCTION,
            view=lambda request: None,
            model=model,
            name_message="{related_model_plural}",
            description_message="{related_model_plural} relationship for {model}",
            message_format_values={"related_model_plural": "Contacts"},
            owner_app_label="bloomerp",
        )

        with patch(
            "bloomerp.router.pgettext",
            side_effect=lambda _context, message: {
                "{related_model_plural}": "{related_model_plural}",
                "{related_model_plural} relationship for {model}": (
                    "{related_model_plural} relacionados con {model}"
                ),
            }.get(message, message),
        ):
            self.assertEqual(route.localized_name, "Contacts")
            self.assertEqual(
                route.localized_description,
                "Contacts relacionados con Account",
            )

    def test_route_extraction_uses_owner_and_context_without_decorator_gettext(self):
        route = BloomerpRoute(
            path="/clientes/",
            route_type=RouteType.APP,
            name="Clientes",
            url_name="clientes",
            view_type=ViewType.FUNCTION,
            view=lambda request: None,
            description="Consultar e gerir clientes.",
            name_message="Clientes",
            description_message="Consultar e gerir clientes.",
            owner_app_label="vendas",
        )
        app = SimpleNamespace(label="vendas")

        with patch("bloomerp.i18n.routes.router.get_routes", return_value=[route]):
            messages = route_messages(app)

        self.assertEqual(
            {(item["context"], item["message"]) for item in messages},
            {
                ("vendas:route:name", "Clientes"),
                ("vendas:route:description", "Consultar e gerir clientes."),
            },
        )

    def test_route_url_name_stays_stable_when_display_name_is_translated(self):
        registry = BloomerpRouteRegistry()

        @registry.register(
            path="/clientes/",
            name="Clientes",
            url_name="clientes",
        )
        def clientes_view(request):
            return None

        route = registry.routes[0]
        with patch(
            "bloomerp.router.pgettext",
            side_effect=lambda _context, message: (
                "Customers" if message == "Clientes" else message
            ),
        ):
            self.assertEqual(route.localized_name, "Customers")

        self.assertEqual(route.url_name, "clientes")

    def test_module_localization_keeps_stable_identity(self):
        module = ModuleConfig(
            id="users",
            code="users",
            name="Utilizadores",
            description="Gerir utilizadores.",
            owner_app_label="vendas",
        )

        with patch(
            "bloomerp.modules.definition.pgettext",
            side_effect=lambda _context, message: {
                "Utilizadores": "Users",
                "Gerir utilizadores.": "Manage users.",
            }.get(message, message),
        ):
            self.assertEqual(module.localized_name, "Users")
            self.assertEqual(module.localized_description, "Manage users.")

        self.assertEqual(module.id, "users")
        self.assertEqual(module.name, "Utilizadores")

    def test_module_extraction_uses_owner_and_context(self):
        module = ModuleConfig(
            id="users",
            code="users",
            name="Utilizadores",
            description="Gerir utilizadores.",
            owner_app_label="vendas",
        )
        app = SimpleNamespace(label="vendas")

        with patch(
            "bloomerp.i18n.modules.module_registry.get_all",
            return_value={"users": module},
        ):
            messages = module_messages(app)

        self.assertEqual(
            {(item["context"], item["message"]) for item in messages},
            {
                ("vendas:module:name", "Utilizadores"),
                ("vendas:module:description", "Gerir utilizadores."),
            },
        )

    def test_component_routes_default_to_non_translatable_and_non_searchable(self):
        registry = BloomerpRouteRegistry()

        @registry.register(
            path="components/clientes/",
            name="components_clientes",
            url_name="components_clientes",
        )
        def clientes_component(request):
            return None

        route = registry.routes[0]
        self.assertFalse(route.translatable)
        self.assertFalse(route.searchable)

    def test_text_choice_labels_are_lazy_translations(self):
        self.assertIsInstance(ActivityLogAction.CHANGE.label, Promise)
        self.assertIsInstance(ActivityLogSource.DETAIL.label, Promise)
        self.assertIsInstance(TodoStatus.IN_PROGRESS.label, Promise)
        self.assertEqual(ActivityLog._meta.get_field("source").choices, ActivityLogSource.choices)

    def test_static_layout_titles_remain_pydantic_safe_and_translate_when_resolved(self) -> None:
        """Use case: Resolve static layout titles. Expected result: Translate at rendering time."""
        layout = Todo.bloomerp_config.detail_view_settings.get_default_layout()

        self.assertIsInstance(layout.rows[0].title, str)
        self.assertEqual(layout.rows[0].title, "Details")

        def todo_model() -> type[Todo]:
            """Return the model behind the simulated content type."""
            return Todo

        def translate_title(message: str) -> str:
            """Translate the section title without needing a compiled catalog."""
            return {"Details": "Detalhes"}.get(message, message)

        content_type = SimpleNamespace(model_class=todo_model)
        with (
            patch("bloomerp.services.sectioned_layout_services.UserPolicyManager"),
            patch(
                "bloomerp.services.sectioned_layout_services.gettext",
                side_effect=translate_title,
            ),
        ):
            rows = resolve_detail_layout_rows(
                layout={"rows": [{"columns": 1, "title": "Details", "items": []}]},
                content_type=content_type,
                user=SimpleNamespace(),
            )

        self.assertEqual(rows[0]["title"], "Detalhes")

    def test_catalog_merge_handles_references_without_line_numbers(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nl" / "LC_MESSAGES" / "django.po"
            merge_messages(
                path,
                "nl",
                "django",
                [{"message": "Invoice", "locations": [("billing.invoice", None)]}],
            )
            merge_messages(
                path,
                "nl",
                "django",
                [{"message": "Invoice", "locations": [("billing.invoice", None)]}],
            )

            self.assertEqual(
                read_catalog(path, "nl", "django")["Invoice"].locations,
                [("billing.invoice", None)],
            )

    def test_catalog_merge_resurrects_obsolete_model_translation_without_duplicate(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nl" / "LC_MESSAGES" / "django.po"
            catalog = Catalog(locale="nl", domain="django")
            catalog.add("Invoice")
            catalog.obsolete["Invoice"] = Message("Invoice", "Factuur")
            save_catalog(catalog, path)

            merge_messages(
                path,
                "nl",
                "django",
                [{"message": "Invoice", "locations": [("billing.invoice", None)]}],
            )

            merged = read_catalog(path, "nl", "django")
            self.assertEqual(merged["Invoice"].string, "Factuur")
            self.assertNotIn("Invoice", merged.obsolete)

    def test_catalog_merge_removes_contextual_obsolete_duplicate(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nl" / "LC_MESSAGES" / "django.po"
            context = "billing:route:name"
            catalog = Catalog(locale="nl", domain="django")
            catalog.add("Invoices", context=context)
            catalog.obsolete["Invoices"] = Message(
                "Invoices",
                "Facturen",
                context=context,
            )
            save_catalog(catalog, path)

            merge_messages(
                path,
                "nl",
                "django",
                [{"message": "Invoices", "context": context}],
            )

            merged = read_catalog(path, "nl", "django")
            self.assertEqual(merged.get("Invoices", context=context).string, "Facturen")
            self.assertFalse(
                any(
                    message.id == "Invoices" and message.context == context
                    for message in merged.obsolete.values()
                )
            )

    def test_catalog_merge_prunes_only_the_generated_contexts(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nl" / "LC_MESSAGES" / "django.po"
            catalog = Catalog(locale="nl", domain="django")
            catalog.add(
                "Contacts",
                "Contacten",
                context="bloomerp:route:name",
            )
            catalog.add("Save", "Opslaan")
            save_catalog(catalog, path)

            merge_messages(
                path,
                "nl",
                "django",
                [
                    {
                        "message": "{related_model_plural}",
                        "context": "bloomerp:route:name",
                    }
                ],
                prune_contexts={"bloomerp:route:name"},
            )

            merged = read_catalog(path, "nl", "django")
            self.assertIsNone(
                merged.get("Contacts", context="bloomerp:route:name")
            )
            self.assertIsNotNone(
                merged.get(
                    "{related_model_plural}",
                    context="bloomerp:route:name",
                )
            )
            self.assertEqual(merged["Save"].string, "Opslaan")

    def test_reconcile_repairs_existing_active_and_obsolete_duplicate(self):
        catalog = Catalog(locale="nl", domain="django")
        active = catalog.add("Invoice")
        catalog.obsolete["Invoice"] = Message("Invoice", "Factuur", flags={"fuzzy"})

        self.assertEqual(reconcile_obsolete_messages(catalog), 1)
        self.assertEqual(active.string, "Factuur")
        self.assertIn("fuzzy", active.flags)
        self.assertNotIn("Invoice", catalog.obsolete)


class TestI18nCatalogs(SimpleTestCase):
    def test_merge_preserves_existing_translation(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "nl" / "LC_MESSAGES" / "djangojs.po"
            merge_messages(
                path,
                "nl",
                "djangojs",
                [{"message": "Search", "locations": [("search.ts", 1)]}],
                prune=True,
            )
            catalog = read_catalog(path, "nl", "djangojs")
            catalog["Search"].string = "Zoeken"
            save_catalog(catalog, path)
            merge_messages(
                path,
                "nl",
                "djangojs",
                [{"message": "Search", "locations": [("other.ts", 2)]}],
                prune=True,
            )

            merged = read_catalog(path, "nl", "djangojs")["Search"]
            self.assertEqual(merged.string, "Zoeken")
            self.assertEqual(merged.locations, [("other.ts", 2)])

    def test_validation_rejects_changed_placeholders(self):
        catalog = Catalog(locale="nl")
        message = catalog.add("Welcome %(name)s", "Welkom %(user)s")

        self.assertIn("placeholder mismatch in plural form 0", validate_message(message))

    def test_approve_clears_fuzzy_only_for_translated_messages(self):
        catalog = Catalog(locale="nl")
        translated = catalog.add("Save", "Opslaan", flags={"fuzzy"})
        untranslated = catalog.add("Cancel", "", flags={"fuzzy"})

        self.assertEqual(approve_translated_messages(catalog), 1)
        self.assertNotIn("fuzzy", translated.flags)
        self.assertIn("fuzzy", untranslated.flags)

    def test_model_metadata_includes_fallback_field_title(self):
        messages = model_messages(apps.get_app_config("bloomerp"), "en")

        self.assertTrue(any(item["message"] == "Field" for item in messages))

    def test_application_field_title_uses_declared_verbose_name(self):
        application_field = ApplicationField(field="first_name")
        model_field = SimpleNamespace(_verbose_name="Customer name")

        with patch.object(application_field, "_get_model_field", return_value=model_field):
            self.assertEqual(application_field.title, "Customer name")

    def test_application_field_title_humanizes_undeclared_label(self):
        application_field = ApplicationField(field="first_name")
        model_field = SimpleNamespace(_verbose_name=None)

        with patch.object(application_field, "_get_model_field", return_value=model_field):
            self.assertEqual(application_field.title, "First Name")


class _FakeStructuredModel:
    def invoke(self, messages):
        return TranslationBatch(
            results=[TranslationResult(index=0, translations=["Welkom %(name)s"])]
        )


class _FakeChatModel:
    def with_structured_output(self, schema):
        self.schema = schema
        return _FakeStructuredModel()


class TestI18nTranslation(SimpleTestCase):
    def test_translation_is_provider_independent_and_marked_fuzzy(self):
        catalog = Catalog(locale="nl")
        message = catalog.add("Welcome %(name)s")

        count = translate_catalog(
            catalog,
            "nl",
            "en",
            BloomerpConfig().i18n.llm,
            model_factory=lambda settings: _FakeChatModel(),
        )

        self.assertEqual(count, 1)
        self.assertEqual(message.string, "Welkom %(name)s")
        self.assertIn("fuzzy", message.flags)


class TestJavaScriptCatalog(SimpleTestCase):
    def test_json_catalog_endpoint_is_available(self):
        response = self.client.get(reverse("bloomerp_javascript_catalog"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("catalog", response.json())
        self.assertIn("plural", response.json())

    def test_json_catalog_combines_compiled_frontend_translation(self):
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "nl"

        response = self.client.get(reverse("bloomerp_javascript_catalog"))

        self.assertEqual(response.json()["catalog"]["Remove row"], "Rij verwijderen")


class TestTemplateTranslations(SimpleTestCase):
    def test_trimmed_multiline_blocktrans_uses_compiled_translation(self):
        template = Template(
            "{% load i18n %}{% blocktrans trimmed %}\n"
            "    Save and Create New\n"
            "{% endblocktrans %}"
        )

        with override("nl"):
            rendered = template.render(Context())

        self.assertEqual(rendered, "Opslaan en nieuw maken")

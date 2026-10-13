import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.exceptions import ImproperlyConfigured
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from bloomerp.templatetags.bloomerp import (
    ACTIVITY_LOG_VALUE_MAX_LENGTH,
    activity_log_html,
)


class ActivityLogHtmlFilterTests(SimpleTestCase):
    def test_activity_log_html_preserves_safe_formatting(self):
        """
        Use case: An activity-log value contains HTML produced by the text editor.
        Expected result: Supported formatting renders as HTML instead of visible markup.
        """
        # 1. Sanitize a value containing supported editor formatting.
        rendered = activity_log_html("<p><strong>Important</strong> update</p>")

        # 2. Verify the safe formatting remains in the rendered value.
        self.assertEqual(str(rendered), "<p><strong>Important</strong> update</p>")

    def test_activity_log_html_removes_executable_content(self):
        """
        Use case: An activity-log value contains scripts and executable HTML attributes.
        Expected result: The value remains readable without executable browser content.
        """
        # 1. Sanitize common script injection vectors.
        rendered = activity_log_html(
            '<p onclick="alert(1)">Update</p>'
            '<script>alert(2)</script>'
            '<a href="javascript:alert(3)">Open</a>'
        )

        # 2. Verify executable tags, attributes, and URL schemes are removed.
        self.assertIn("Update", str(rendered))
        self.assertNotIn("<script", str(rendered))
        self.assertNotIn("onclick", str(rendered))
        self.assertNotIn("javascript:", str(rendered))

    def test_activity_log_html_truncates_visible_text_and_closes_tags(self):
        """
        Use case: An activity-log value contains more text than the sidebar should display.
        Expected result: Visible text is capped and the resulting HTML remains well formed.
        """
        # 1. Sanitize a long formatted value.
        rendered = str(
            activity_log_html(
                f"<p><strong>{'a' * (ACTIVITY_LOG_VALUE_MAX_LENGTH + 50)}</strong></p>"
            )
        )

        # 2. Verify truncation adds an ellipsis and preserves closing tags.
        self.assertIn("…", rendered)
        self.assertTrue(rendered.endswith("</strong></p>"))
        self.assertLessEqual(
            rendered.count("a"),
            ACTIVITY_LOG_VALUE_MAX_LENGTH,
        )

    def test_activity_log_template_uses_sanitized_html_for_changed_values(self):
        """
        Use case: The detail sidebar renders an activity entry containing editor HTML.
        Expected result: Formatting renders in both the summary and details without scripts.
        """
        # 1. Build an activity entry containing safe formatting and script injection vectors.
        value = '<strong>Visible</strong><script>alert("xss")</script>'
        entry = SimpleNamespace(
            action="CHANGE",
            actor=None,
            payload=[{"field": "notes", "from": "", "to": value}],
            source="DETAIL",
            summary_string=f"System changed the field 'notes' to {value}",
            timestamp=timezone.now(),
        )

        # 2. Render the same template used by the activity-log component.
        rendered = render_to_string(
            "views/generic/detail/activity.html",
            {"queryset": [entry]},
        )

        # 3. Verify formatting renders in both locations while scripts never reach the page.
        self.assertEqual(rendered.count("<strong>Visible</strong>"), 2)
        self.assertNotIn("<script", rendered)
        self.assertNotIn("&lt;strong&gt;", rendered)


class ViteBundleTemplateTests(SimpleTestCase):
    def render_built_bundle(self, filename: str, static_url: str = "/static/") -> str:
        """Render the production snippet against a compiled entry manifest."""
        with TemporaryDirectory() as directory:
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(
                json.dumps({"ts/entry.ts": {"file": filename, "isEntry": True}}),
                encoding="utf-8",
            )
            with override_settings(DEBUG=False, STATIC_URL=static_url):
                with patch("django.contrib.staticfiles.finders.find", return_value=str(manifest_path)):
                    return render_to_string("snippets/vite_bundle.html")

    def test_built_bundle_uses_the_same_hashed_url_as_lazy_imports(self) -> None:
        """Keep the page's module identity consistent with Whiteboard lazy imports."""
        rendered = self.render_built_bundle("main-first-build.js")
        self.assertIn('src="/static/bloomerp/js/dist/main-first-build.js"', rendered)
        self.assertNotIn("?v=", rendered)
        self.assertNotIn("dist/main.js", rendered)

    def test_rebuild_changes_the_entry_url_without_a_package_version_change(self) -> None:
        """Invalidate browser caches whenever the compiled application changes."""
        first = self.render_built_bundle("main-first-build.js")
        second = self.render_built_bundle("main-second-build.js")
        self.assertIn("main-first-build.js", first)
        self.assertIn("main-second-build.js", second)
        self.assertNotEqual(first, second)

    def test_built_bundle_respects_a_cdn_static_url(self) -> None:
        """Resolve the hashed entry through Django's configured static storage."""
        rendered = self.render_built_bundle("main-cdn-build.js", "https://cdn.example.com/assets/")
        self.assertIn('src="https://cdn.example.com/assets/bloomerp/js/dist/main-cdn-build.js"', rendered)

    @override_settings(DEBUG=False)
    @patch("django.contrib.staticfiles.finders.find", return_value=None)
    def test_missing_manifest_reports_the_required_build(self, _find: MagicMock) -> None:
        """Report missing compiled assets instead of falling back to the stale entry."""
        with self.assertRaisesMessage(ImproperlyConfigured, "Run npm run build:js"):
            render_to_string("snippets/vite_bundle.html")

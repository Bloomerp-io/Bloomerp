"""Focused non-database checks for provider and transport contracts."""

from dataclasses import replace
from unittest.mock import AsyncMock, Mock, patch
from django.test import SimpleTestCase
from bloomerp.communication.builtins.instant_messaging.builtins.bloomerp import InternalIMAdapter
from bloomerp.communication.builtins.instant_messaging.builtins.slack import SlackAdapter
from bloomerp.communication.builtins.instant_messaging.builtins.whatsapp import WhatsAppAdapter
from bloomerp.communication.builtins.instant_messaging.definition import (
    IMAdapterNotReady, IMConnectionContext, IMOutboundMessage,
    IMProviderDefinition, IMUnsupportedOperation,
)
from bloomerp.communication.builtins.instant_messaging.registry import IM_PROVIDER_REGISTRY, IMProviderRegistry


class TestIMContracts(SimpleTestCase):
    """Exercise pure contracts that do not belong to request or model scenarios."""

    def test_extension_hook_accepts_callable_and_import_path(self) -> None:
        """Resolve both supported hook forms to the same executable function."""
        from bloomerp.utils.callables import resolve_hook
        from bloomerp.utils.rich_text import format_content

        for hook in (format_content, "bloomerp.utils.rich_text.format_content"):
            self.assertEqual(resolve_hook(hook)("<p>Hello</p>", "plain"), "Hello")

    def test_extension_hook_rejects_non_callable_import(self) -> None:
        """Fail clearly when an extension points a hook at a data object."""
        from bloomerp.utils.callables import resolve_hook

        with self.assertRaisesRegex(TypeError, "must resolve to a callable"):
            resolve_hook("bloomerp.utils.rich_text.TAGS")

    def test_registry_rejects_ambiguous_identifiers(self) -> None:
        """Use case: Extensions register aliases that collide with stored keys.
        Expected result: Both lookup paths stay unambiguous and duplicates fail.
        """
        # 1. Register the native provider in an isolated registry.
        registry = IMProviderRegistry(IMProviderDefinition)
        definition = IM_PROVIDER_REGISTRY.get("internal")
        registry.register("NATIVE", definition)
        self.assertIs(registry.get("internal"), definition)
        self.assertIs(registry.get("NATIVE"), definition)
        # 2. Reject duplicate persisted keys and aliases of another stored key.
        with self.assertRaises(ValueError):
            registry.register("SECOND", definition)
        with self.assertRaises(ValueError):
            registry.register("internal", IM_PROVIDER_REGISTRY.get("slack"))

    def test_provider_identity_falls_back_to_address(self) -> None:
        """Use the provider address as the display name when no name is supplied."""
        definition = IM_PROVIDER_REGISTRY.get("whatsapp")
        self.assertEqual(
            definition.resolve_identity({"phone": "+32470000001"})["displayName"],
            "+32470000001",
        )

    def test_internal_delivery_only_invalidates_authorized_recipients(self) -> None:
        """Use case: A committed message has duplicate authorized recipients.
        Expected result: Each recipient gets one ID-only event and no message body.
        """
        # 1. Supply already-resolved recipients and a private message body.
        adapter = InternalIMAdapter(IMConnectionContext("native", "internal"))
        message = IMOutboundMessage(
            "message-1", "conversation-1", "send-1", "1", "Private body",
            recipient_user_ids=("2", "2", "3"),
        )
        layer = Mock(group_send=AsyncMock())
        # 2. Dispatch through the channel-layer boundary without persistence.
        with patch("bloomerp.communication.builtins.instant_messaging.builtins.bloomerp.get_channel_layer", return_value=layer):
            result = adapter.send_message(message)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(layer.group_send.await_count, 2)
        for user_id in ("2", "3"):
            layer.group_send.assert_any_await(f"user_{user_id}", {
                "type": "notify", "payload": {
                    "action": "im.message.created", "conversation_id": "conversation-1",
                    "message_id": "message-1",
                },
            })

    def test_draft_external_adapters_fail_closed(self) -> None:
        """Use case: A caller uses an unfinished external integration.
        Expected result: Connection, send and webhook handling never claim success.
        """
        # 1. Bind integrations to their respective account contexts.
        message = IMOutboundMessage("m", "c", "key", "user", "Hello")
        for adapter_class in (SlackAdapter, WhatsAppAdapter):
            with self.subTest(provider=adapter_class.provider_key):
                adapter = adapter_class(IMConnectionContext("connection", adapter_class.provider_key))
                self.assertFalse(adapter.validate_connection().valid)
                # 2. Neither dispatch nor inbound verification may silently succeed.
                with self.assertRaises(IMAdapterNotReady):
                    adapter.send_message(message)
                with self.assertRaises(IMAdapterNotReady):
                    adapter.receive_events(b'{}', {})

    def test_connection_scope_and_contact_discovery(self) -> None:
        """Use case: Mismatched credentials or unsupported contact lookup is supplied.
        Expected result: Provider mismatch and ordinary WhatsApp directory calls fail.
        """
        # 1. Reject cross-provider binding and keep credentials out of repr.
        with self.assertRaises(ValueError):
            SlackAdapter(IMConnectionContext("connection", "whatsapp"))
        context = IMConnectionContext("connection", "whatsapp", credentials={"token": "test-secret"})
        self.assertNotIn("test-secret", repr(context))
        # 2. Distinguish standard addressing from Coexistence synchronization.
        adapter = WhatsAppAdapter(context)
        with self.assertRaises(IMUnsupportedOperation):
            adapter.discover_recipients("Jane")
        with self.assertRaises(IMUnsupportedOperation):
            adapter.request_contact_sync()
        coexistence = WhatsAppAdapter(replace(context, settings={"coexistence": "true"}))
        with self.assertRaises(IMAdapterNotReady):
            coexistence.request_contact_sync()

    def test_editor_content_formats_for_each_provider(self) -> None:
        """Preserve supported formatting while removing HTML and reference metadata."""
        message = IMOutboundMessage('message', 'conversation', 'retry', 'sender', 'Hello team', body_html='<p>Hello <strong>team</strong> &amp; &lt;@everyone&gt;</p><p><span data-reference-kind="object" data-target-id="secret-id">Order 42</span></p>')
        slack = SlackAdapter(IMConnectionContext('slack', 'slack')).format_message(message)
        whatsapp = WhatsAppAdapter(IMConnectionContext('wa', 'whatsapp')).format_message(message)
        self.assertEqual(slack, 'Hello *team* &amp; &lt;@everyone&gt;\nOrder 42')
        self.assertEqual(whatsapp, 'Hello *team* & <@everyone>\nOrder 42')
        self.assertNotIn('secret-id', slack)

    def test_editor_links_and_code_convert_safely(self) -> None:
        """Keep safe links and code while dropping executable HTML attributes."""
        from bloomerp.communication.builtins.instant_messaging.content import format_content, sanitize_html
        html = '<p><a href="https://example.com" onclick="bad()">Example</a></p><pre><code>x &lt; y</code></pre><script>bad()</script>'
        self.assertEqual(format_content(html, 'slack'), '<https://example.com|Example>\n```x &lt; y```')
        self.assertNotIn('onclick', sanitize_html(html))
        self.assertNotIn('bad()', sanitize_html(html))

    def test_internal_html_retains_editor_presentation(self) -> None:
        """Keep editor headings, alignment, code and tables without active styling."""
        from bloomerp.communication.builtins.instant_messaging.content import sanitize_html
        html = '<h2 class="text-2xl font-bold mb-1 fixed" style="text-align: center; position: fixed" onclick="bad()">Heading</h2><pre data-text-editor-code-block="true"><code>print(1)</code></pre><table class="w-full table-fixed"><tbody><tr><td colspan="2">Cell</td></tr></tbody></table>'
        rendered = sanitize_html(html)
        self.assertIn('class="text-2xl font-bold mb-1"', rendered)
        self.assertIn('text-align: center', rendered)
        self.assertIn('data-text-editor-code-block="true"', rendered)
        self.assertIn('<table class="w-full table-fixed">', rendered)
        self.assertIn('colspan="2"', rendered)
        self.assertNotIn('position:', rendered)
        self.assertNotIn('mb-1 fixed', rendered)
        self.assertNotIn('onclick', rendered)

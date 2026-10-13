from django.test import SimpleTestCase

from bloomerp.communication.builtins.emails.email_providers import EmailProviderDefinition
from bloomerp.communication.builtins.emails.providers.imap_smtp import ImapSmtpAdapter
from bloomerp.communication.builtins.emails.registry import EMAIL_PROVIDER_REGISTRY
from bloomerp.communication.definition import (
    InboxEventSource,
    InboxFolderTypeDefinition,
    InboxItemTypeDefinition,
)
from bloomerp.communication.inbox_sources import InboxSourceRegistry
from bloomerp.communication.registry import INBOX_FOLDER_REGISTRY
from bloomerp.models.communication.email_account import EmailAccount
from bloomerp.models.communication.inbox.inbox_folder import InboxFolder
from bloomerp.models.communication.inbox.inbox_item import InboxItem


class TestCommunicationRegistries(SimpleTestCase):
    def test_registered_email_provider_is_resolved_and_added_to_model_choices(self):
        """
        Use case: Another app registers an email provider after model import.
        Expected result: Runtime lookup and the provider field include that provider.
        """
        # 1. Register a provider using a symbolic extension key.
        definition = EmailProviderDefinition(
            key="external_mail",
            name="External Mail",
            description="A provider supplied by another app.",
            icon="fa-solid fa-envelope",
            adapter_class=ImapSmtpAdapter,
        )
        EMAIL_PROVIDER_REGISTRY.register("EXTERNAL_MAIL", definition)
        self.addCleanup(EMAIL_PROVIDER_REGISTRY.unregister, "EXTERNAL_MAIL")

        # 2. Resolve both the symbolic key and the persisted provider value.
        self.assertIs(EMAIL_PROVIDER_REGISTRY.EXTERNAL_MAIL, definition)
        self.assertIs(EMAIL_PROVIDER_REGISTRY.get("external_mail"), definition)

        # 3. Confirm callable model choices see the late registration.
        provider_field = EmailAccount._meta.get_field("provider")
        self.assertIn(("external_mail", "External Mail"), provider_field.flatchoices)

    def test_registered_inbox_folder_is_added_to_folder_and_item_choices(self):
        """
        Use case: Another app registers a folder type with its own item type.
        Expected result: Folder lookup plus both model choice lists include it.
        """
        # 1. Register an external folder and inbox-item definition.
        item_type = InboxItemTypeDefinition(
            key="external_item",
            name="External Item",
            name_plural="External Items",
        )
        definition = InboxFolderTypeDefinition(
            key="external_folder",
            name="External Folder",
            item_type=item_type,
        )
        INBOX_FOLDER_REGISTRY.register("EXTERNAL_FOLDER", definition)
        self.addCleanup(INBOX_FOLDER_REGISTRY.unregister, "EXTERNAL_FOLDER")

        # 2. Resolve both the symbolic and persisted folder keys.
        self.assertIs(INBOX_FOLDER_REGISTRY.EXTERNAL_FOLDER, definition)
        self.assertIs(INBOX_FOLDER_REGISTRY.get("external_folder"), definition)
        self.assertIs(
            INBOX_FOLDER_REGISTRY.get_item_type_by_key("external_item"),
            item_type,
        )

        # 3. Confirm both callable model choices see the late registration.
        folder_field = InboxFolder._meta.get_field("type")
        item_field = InboxItem._meta.get_field("item_type")
        self.assertIn(("external_folder", "External Folder"), folder_field.flatchoices)
        self.assertIn(("external_item", "External Item"), item_field.flatchoices)

    def test_duplicate_persisted_keys_are_rejected(self):
        """
        Use case: Two extensions register definitions with the same stored key.
        Expected result: The second registration fails even if its symbolic key differs.
        """
        # 1. Build a provider whose persisted key collides with the built-in provider.
        duplicate = EmailProviderDefinition(
            key="imap",
            name="Duplicate IMAP",
            description="Invalid duplicate provider.",
            icon="fa-solid fa-envelope",
            adapter_class=ImapSmtpAdapter,
        )

        # 2. Verify the registry protects persisted identifiers from ambiguity.
        with self.assertRaisesMessage(ValueError, "'imap' is already registered"):
            EMAIL_PROVIDER_REGISTRY.register("DUPLICATE_IMAP", duplicate)

    def test_late_registered_folder_contributes_default_sources(self):
        """
        Use case: An extension registers a folder after core defaults were loaded.
        Expected result: Its declared default sources are discovered on the next lookup.
        """
        # 1. Ensure core defaults are loaded before registering the extension.
        InboxSourceRegistry.load_defaults()
        source = InboxEventSource(
            key="external.folder.event",
            folder_qs_resolver=lambda **kwargs: None,
            handler=lambda folders, **kwargs: None,
        )
        definition = InboxFolderTypeDefinition(
            key="external_source_folder",
            name="External Source Folder",
            default_sources=[source],
        )

        # 2. Register the folder after that initial load.
        INBOX_FOLDER_REGISTRY.register("EXTERNAL_SOURCE_FOLDER", definition)
        self.addCleanup(
            INBOX_FOLDER_REGISTRY.unregister,
            "EXTERNAL_SOURCE_FOLDER",
        )
        self.addCleanup(
            InboxSourceRegistry._loaded_default_sources.discard,
            (definition.key, source.key),
        )
        self.addCleanup(InboxSourceRegistry._sources.pop, source.key, None)

        # 3. Confirm a later lookup incrementally loads the extension source.
        registered_sources = InboxSourceRegistry.for_folder(definition.key)
        self.assertEqual(len(registered_sources), 1)
        self.assertIs(registered_sources[0].source, source)

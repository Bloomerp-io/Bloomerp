"""Focused rendering and catalog regressions for the remaining UI translations."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.apps import apps
from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext, override

from bloomerp.config.definition import BloomerpI18nLLMSettings
from bloomerp.field_types.builtins.text import CHAR_FIELD, CHOICE_FIELD
from bloomerp.i18n.models import model_messages
from bloomerp.i18n.translator import create_langchain_model
from bloomerp.models import User
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.project_management.todo import Todo
from bloomerp.permissions.manager import field_access_annotation_name
from bloomerp.templatetags.bloomerp import render_dataview_value


class TestRemainingInternationalization(SimpleTestCase):
    """Check pure rendering contracts without database or browser fixtures."""

    def test_empty_preference_chooser_translates_creation_phrase(self) -> None:
        """
        Use case: Open an empty tabs or Inbox preference chooser.
        Expected result: Translate the full creation phrase and accessible controls.
        """
        # 1. Supply localized model metadata to the real chooser fragment.
        for language, model_label, heading, empty, name in [
            ('nl', 'tabbladvoorkeur', 'Nieuwe tabbladvoorkeur', 'Er zijn nog geen voorkeuren beschikbaar.', 'Naam van de voorkeur'),
            ('fr', 'préférence d’onglets', 'Nouvelle préférence d’onglets', 'Aucune préférence disponible pour le moment.', 'Nom de la préférence'),
        ]:
            with self.subTest(language=language), override(language):
                html = render_to_string('components/preferences/select.html', {'model': 'UserDetailViewTabsPreference', 'model_verbose_name': model_label, 'preferences': [], 'scope': {}})
                # 2. Verify full phrases and the accessible input name.
                self.assertIn(heading, html)
                self.assertIn(empty, html)
                self.assertIn(f'aria-label="{name}"', html)

    def test_delete_confirmation_translates_plural_counts(self) -> None:
        """
        Use case: Preview deletion of one or several related records.
        Expected result: Translate the full confirmation with correct plural forms.
        """
        # 1. Preview each count without submitting a destructive operation.
        for language, singular, plural in [
            ('nl', 'Dit verwijdert in totaal 1 object, inclusief gerelateerde records.', 'Dit verwijdert in totaal 2 objecten, inclusief gerelateerde records.'),
            ('fr', 'Cela supprimera 1 objet au total, y compris les enregistrements liés.', 'Cela supprimera 2 objets au total, y compris les enregistrements liés.'),
        ]:
            for count, phrase in [(1, singular), (2, plural)]:
                with self.subTest(language=language, count=count), override(language):
                    html = render_to_string('views/generic/detail/delete.html', {'object': 'Customer name', 'total_objects': count})
                    # 2. Preserve customer text while translating the surrounding sentence.
                    self.assertIn(phrase, html)
                    self.assertIn('Customer name', html)
                    self.assertNotIn('You are about to delete', html)

    def test_activity_dates_translate_the_complete_relative_phrase(self) -> None:
        """
        Use case: Read a change entry and its relative time in another locale.
        Expected result: Translate word order and disclosure while preserving values.
        """
        # 1. Render a deterministic history entry rather than creating audit records.
        now = timezone.now()
        entry = SimpleNamespace(timestamp=now - timedelta(days=1), actor='Customer name', action='CHANGE', summary_string='Customer summary', payload=[{'field': 'title', 'from': 'Customer old value', 'to': 'Customer new value'}])
        # 2. Check the full phrase and controls under each language.
        for language, elapsed, control in [('nl', '1 dag geleden', 'Wijzigingen bekijken'), ('fr', 'Il y a 1 jour', 'Voir les modifications')]:
            with self.subTest(language=language), override(language):
                html = render_to_string('views/generic/detail/activity.html', {'queryset': [entry]})
                self.assertIn(elapsed, html.replace('\u00a0', ' '))
                self.assertIn(control, html)
                self.assertIn('Customer old value', html)
                self.assertNotIn(' ago', html)

    def test_translator_omits_unspecified_temperature(self) -> None:
        """
        Use case: Translate with default or explicit sampling configuration.
        Expected result: Omit unspecified temperature and preserve explicit zero.
        """
        # 1. Substitute the optional provider integration.
        initialize = Mock()
        modules = {
            'langchain': SimpleNamespace(),
            'langchain.chat_models': SimpleNamespace(init_chat_model=initialize),
        }
        # 2. Check provider defaults and explicit overrides independently.
        for temperature in (None, 0.0, 0.5):
            with self.subTest(temperature=temperature), patch.dict('sys.modules', modules):
                initialize.reset_mock()
                config = BloomerpI18nLLMSettings(temperature=temperature)
                create_langchain_model(config)
                kwargs: dict[str, object] = {'model_provider': 'openai'}
                if temperature is not None:
                    kwargs['temperature'] = temperature
                initialize.assert_called_once_with(config.model, **kwargs)

    def test_computed_field_labels_are_extracted(self) -> None:
        """
        Use case: Display a computed Todo field in another locale.
        Expected result: Its humanized label is available for translation.
        """
        # 1. Extract metadata, including properties without Django model fields.
        messages = model_messages(apps.get_app_config('bloomerp'), 'en')
        # 2. Check the exact computed label used by ApplicationField.title.
        self.assertTrue(any(message['message'] == 'Is Completed' for message in messages))

    def test_choice_cards_use_localized_display_values(self) -> None:
        """
        Use case: Render a choice on a Kanban card in Dutch or French.
        Expected result: Display its declared label and preserve ordinary text.
        """
        # 1. Use unsaved records because rendering does not need persistence.
        todo = Todo(priority='medium', title='Customer-authored medium')
        # 2. Verify both choice-capable field types and ordinary text.
        for language, expected in [('nl', 'Gemiddeld'), ('fr', 'Moyenne')]:
            with self.subTest(language=language), override(language):
                for field_type in (CHAR_FIELD, CHOICE_FIELD):
                    self.assertEqual(field_type.render_value(ApplicationField(field='priority'), todo), expected)
                    self.assertEqual(field_type.render_value(ApplicationField(field='title'), todo), todo.title)

    def test_choice_display_keeps_filter_keys_and_field_denials(self) -> None:
        """
        Use case: Show a translated choice in an editable data view.
        Expected result: Keep the stored filter key and conceal denied values.
        """
        # 1. Resolve only the presentation metadata, without database fixtures.
        field = ApplicationField(pk=123, field='priority')
        todo = Todo(title='Customer title', priority='medium')
        with override('nl'), patch.object(field, 'get_field_type', return_value=CHOICE_FIELD):
            context = render_dataview_value(todo, field, User())
            # 2. Display the label while preserving the value used by filtering.
            self.assertEqual(context['value'], 'Gemiddeld')
            self.assertEqual(context['data_value'], 'medium')
            # 3. Respect the existing per-field denial annotation for both values.
            setattr(todo, field_access_annotation_name(field), False)
            hidden = render_dataview_value(todo, field, User())
            self.assertEqual(hidden['value'], '')
            self.assertEqual(hidden['data_value'], '')

    def test_catalog_labels_keep_actions_and_feedback_distinct(self) -> None:
        """
        Use case: View Todo metadata and completion controls in Dutch or French.
        Expected result: Labels retain their meaning and actions use imperative wording.
        """
        # 1. Specify independently reviewed phrases instead of comparing translations to themselves.
        phrases = {
            'nl': {
                'Mark as Completed': 'Markeer als voltooid',
                'Todo marked as completed.': 'Taak gemarkeerd als voltooid.',
                'The user to whom the todo is assigned': 'De gebruiker aan wie de taak is toegewezen',
                'Timeline': 'Tijdlijn',
                'Is Completed': 'Is voltooid',
                'Overview': 'Overzicht',
                'Move': 'Verplaatsen',
                'Rename': 'Hernoemen',
            },
            'fr': {
                'Mark as Completed': 'Marquer comme terminée',
                'Todo marked as completed.': 'Tâche marquée comme terminée.',
                'The user to whom the todo is assigned': 'L’utilisateur auquel la tâche est assignée',
                'Timeline': 'Chronologie',
                'Is Completed': 'Est terminée',
                'Overview': 'Vue d’ensemble',
                'Move': 'Déplacer',
                'Rename': 'Renommer',
            },
        }
        # 2. Resolve the compiled runtime catalog under each active language.
        for language, messages in phrases.items():
            with self.subTest(language=language), override(language):
                for source, expected in messages.items():
                    self.assertEqual(gettext(source), expected)

    def test_inbox_empty_state_translates_full_phrases(self) -> None:
        """
        Use case: Open Inbox without a selected inbox.
        Expected result: Translate its complete onboarding flow and preference chooser.
        """
        # 1. Render the actual Cotton-backed view rather than an isolated translation tag.
        for language, expected in [
            ('nl', ['Inbox aanmaken', 'Maak een inbox aan of selecteer er een die met u is gedeeld.', 'Gedeelde inbox selecteren', 'Standaard aanmaken', 'Aangepaste inbox aanmaken']),
            ('fr', ['Créer une boîte de réception', 'Créez une boîte de réception ou sélectionnez-en une qui a été partagée avec vous.', 'Sélectionner une boîte de réception partagée', 'Créer par défaut', 'Créer une boîte personnalisée']),
        ]:
            with self.subTest(language=language), override(language):
                html = render_to_string('views/communication/inbox.html', {})
                # 2. Assert each full phrase in the rendered flow.
                for phrase in expected:
                    self.assertIn(phrase, html)

    def test_frontend_catalog_contains_editor_and_relation_controls(self) -> None:
        """
        Use case: Initialize editor and relationship widgets after loading translations.
        Expected result: Their commands and accessible names are in the frontend catalog.
        """
        # 1. Request the real catalog endpoint using each language cookie.
        for language, expected in [
            ('nl', {'Code Block': 'Codeblok', 'Show formatting toolbar': 'Opmaakwerkbalk tonen', 'No results': 'Geen resultaten', 'Remove {label}': '{label} verwijderen'}),
            ('fr', {'Code Block': 'Bloc de code', 'Show formatting toolbar': 'Afficher la barre de mise en forme', 'No results': 'Aucun résultat', 'Remove {label}': 'Supprimer {label}'}),
        ]:
            self.client.cookies['django_language'] = language
            response = self.client.get(reverse('bloomerp_javascript_catalog'))
            # 2. Verify extraction and compilation preserve all exact message keys.
            with self.subTest(language=language):
                for source, translation in expected.items():
                    self.assertEqual(response.json()['catalog'][source], translation)

"""Browser regressions for translated asynchronous controls and locale navigation."""
from functools import partial

from django.conf import settings
from django.urls import reverse
from playwright.sync_api import expect

from bloomerp.models.project_management.todo import Todo
from bloomerp.models.project_management.todo_label import TodoLabel
from bloomerp.tests import base
from bloomerp.tests.base import E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_list_view_url


class TestInternationalizationE2E(base.BloomerpE2ETestCase):
    """Exercise widget initialization and persistent sidebar forms in both locales."""

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe localized detail, list, and navigation contracts as browser scenarios."""
        todo = Todo.objects.create(title='Customer-authored title', assigned_to=self.admin_user, content='<p>Customer-authored content</p>')
        label = TodoLabel.objects.create(name='Customer-authored label', color='#123456')
        todo.labels.add(label)
        scenarios: list[E2ERequestScenario] = []
        for language, target in [('nl', 'fr'), ('fr', 'nl')]:
            scenarios.append(E2ERequestScenario(
                name=f'{language}: async detail controls and locale switch after navigation',
                user=self.admin_user,
                url=todo.get_absolute_url(),
                prepare=partial(self.set_locale_cookie, language),
                actions=[
                    E2EAction(name='Wait for translated detail widgets', execute=partial(self.check_detail_widgets, language)),
                    E2EAction(name='Open the global search modal', execute=partial(self.check_global_search, language)),
                    E2EAction(name='Open localized preference controls', execute=partial(self.check_preferences, language)),
                    E2EAction(name='Navigate to Inbox using HTMX', execute=self.navigate_to_inbox),
                    E2EAction(name='Change language from the persistent sidebar', execute=partial(self.submit_locale_change, target), validators=partial(self.check_inbox_locale, target)),
                ],
            ))
            scenarios.append(E2ERequestScenario(
                name=f'{language}: list toolbar finishes rendering with localized labels',
                user=self.admin_user,
                url=reverse(get_list_view_url(Todo)),
                prepare=partial(self.set_locale_cookie, language),
                actions=[E2EAction(name='Wait for localized list controls', execute=partial(self.check_list_controls, language))],
            ))
        return scenarios

    def set_locale_cookie(self, language: str) -> None:
        """Set the language before the scenario's full-page navigation."""
        self.context.add_cookies([{'name': settings.LANGUAGE_COOKIE_NAME, 'value': language, 'url': self.live_server_url}])

    def check_detail_widgets(self, language: str) -> None:
        """Wait for initialized widgets and check full labels without changing records."""
        phrases = {
            'nl': ['Markeer als voltooid', 'De gebruiker aan wie de taak is toegewezen', 'Tijdlijn', 'Is Voltooid'],
            'fr': ['Marquer comme terminée', 'L’utilisateur auquel la tâche est assignée', 'Chronologie', 'Est Terminée'],
        }
        for phrase in phrases[language]:
            expect(self.page.get_by_text(phrase, exact=True).first).to_be_visible()
        editor = self.page.locator('[bloomerp-component="bloomerp-text-editor"][data-name="content"]')
        expect(editor).to_have_attribute('data-component-initialized', 'true')
        hidden_input = editor.locator('[data-text-editor-input]')
        content = hidden_input.input_value()
        reveal = 'Opmaakwerkbalk tonen' if language == 'nl' else 'Afficher la barre de mise en forme'
        editor.get_by_role('button', name=reveal, exact=True).click()
        commands = ['Codeblok', 'Kop 1', 'Afbeelding', 'Opsomming', 'Genummerde lijst', 'Checklist', 'Tabel'] if language == 'nl' else ['Bloc de code', 'Titre 1', 'Image', 'Liste à puces', 'Liste numérotée', 'Liste de contrôle', 'Tableau']
        for command in commands:
            expect(editor.get_by_role('button', name=command, exact=True)).to_be_visible()
        hide = 'Opmaakwerkbalk verbergen' if language == 'nl' else 'Masquer la barre de mise en forme'
        editor.get_by_role('button', name=hide, exact=True).click()
        expect(hidden_input).to_have_value(content)
        relation = self.page.locator('[bloomerp-component="foreign-field-widget"][data-field-name="labels"]')
        remove = 'Customer-authored label verwijderen' if language == 'nl' else 'Supprimer Customer-authored label'
        expect(relation.get_by_role('button', name=remove, exact=True)).to_be_visible()
        relation.locator('input[type="text"]').fill('zzqa_no_such_label')
        dropdown = self.page.locator('.foreign-field-dropdown:visible')
        expect(dropdown.get_by_text('Geen resultaten' if language == 'nl' else 'Aucun résultat', exact=True)).to_be_visible()
        expect(dropdown.get_by_text('Nieuw aanmaken' if language == 'nl' else 'Créer', exact=True)).to_be_visible()
        expect(dropdown.get_by_text('Geavanceerde zoekopdracht' if language == 'nl' else 'Recherche avancée', exact=True)).to_be_visible()
        relation.locator('input[type="text"]').fill('')
        self.page.get_by_text('Customer-authored title', exact=True).first.click()

    def check_preferences(self, language: str) -> None:
        """Inspect the asynchronous chooser without saving preferences."""
        trigger = 'Tabbladvoorkeur selecteren' if language == 'nl' else 'Sélectionner une préférence d’onglets'
        self.page.get_by_role('button', name=trigger, exact=True).click()
        panel = self.page.locator('#select-preference-dropdown-UserDetailViewTabsPreference')
        chooser = panel.locator('[bloomerp-component="select-preference"]')
        expect(chooser).to_have_attribute('data-component-initialized', 'true')
        for label in (['Voorkeur hernoemen', 'Voorkeur delen', 'Voorkeur verwijderen'] if language == 'nl' else ['Renommer la préférence', 'Partager la préférence', 'Supprimer la préférence']):
            expect(chooser.get_by_role('button', name=label, exact=True).first).to_be_visible()
        expect(panel.get_by_role('textbox', name='Naam van de voorkeur' if language == 'nl' else 'Nom de la préférence', exact=True)).to_be_visible()
        expect(panel.get_by_role('button', name='Opslaan' if language == 'nl' else 'Enregistrer', exact=True)).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(panel).to_be_hidden()

    def check_global_search(self, language: str) -> None:
        """Check the complete global search heading and prompt in the visible modal."""
        self.page.locator('#global-search-btn').click()
        modal = self.page.locator('#global-search-modal')
        title = 'Zoeken' if language == 'nl' else 'Rechercher'
        prompt = 'Zoek of typ een opdracht' if language == 'nl' else 'Rechercher ou saisir une commande'
        expect(modal.get_by_role('heading', name=title, exact=True)).to_be_visible()
        expect(modal.get_by_placeholder(prompt, exact=True)).to_be_visible()
        self.page.keyboard.press('Escape')
        expect(modal).to_be_hidden()

    def navigate_to_inbox(self) -> None:
        """Use the HTMX link so the original locale form remains mounted."""
        self.page.locator('#inbox-btn').click()
        expect(self.page).to_have_url(self.live_server_url + reverse('inbox'))
        expect(self.page.locator('#create-inbox-panel')).to_be_visible()

    def submit_locale_change(self, language: str) -> None:
        """Submit the persistent language form through its native submit event."""
        self.page.evaluate(f'document.querySelector("form[data-language-switch]:has(input[name=language][value={language}])").requestSubmit()')

    def check_inbox_locale(self, language: str) -> None:
        """Verify submission stays on Inbox and renders its translated onboarding flow."""
        expect(self.page).to_have_url(self.live_server_url + reverse('inbox'))
        expected = ['Inbox aanmaken', 'Maak een inbox aan of selecteer er een die met u is gedeeld.', 'Gedeelde inbox selecteren', 'Standaard aanmaken', 'Aangepaste inbox aanmaken'] if language == 'nl' else ['Créer une boîte de réception', 'Créez une boîte de réception ou sélectionnez-en une qui a été partagée avec vous.', 'Sélectionner une boîte de réception partagée', 'Créer par défaut', 'Créer une boîte personnalisée']
        for phrase in expected:
            expect(self.page.get_by_text(phrase, exact=True).first).to_be_visible()

    def check_list_controls(self, language: str) -> None:
        """Wait for the data view fragment and inspect translated toolbar actions."""
        labels = ['Exporteren', 'Bulkacties', 'Filter', 'Weergave', 'Toevoegen'] if language == 'nl' else ['Exporter', 'Actions groupées', 'Filtre', 'Affichage', 'Ajouter']
        for label in labels:
            expect(self.page.get_by_role('button', name=label, exact=True).first).to_be_visible()
        expect(self.page.get_by_placeholder('Zoeken...' if language == 'nl' else 'Rechercher...').first).to_be_visible()

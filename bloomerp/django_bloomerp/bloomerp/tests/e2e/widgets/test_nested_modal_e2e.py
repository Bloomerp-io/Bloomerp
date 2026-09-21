import re

from django.urls import reverse
from playwright.sync_api import Locator, Route, expect

from bloomerp.tests.base import BloomerpE2ETestCase, E2EAction, E2ERequestScenario
from bloomerp.utils.models import get_create_view_url


class TestNestedModalE2E(BloomerpE2ETestCase):
    """Exercise real HTMX nesting, validation, selection and dialog lifecycles."""

    create_foreign_models = True
    auto_create_customers = False
    pending_creation_request: Route | None = None

    def get_test_scenarios(self) -> list[E2ERequestScenario]:
        """Describe successful nested creation and cancellation without losing drafts."""
        url = reverse(get_create_view_url(self.CustomerModel))
        return [
            E2ERequestScenario(
                name="Closing a loading modal cancels its request without reopening it",
                user=self.admin_user,
                url=url,
                actions=[E2EAction(name="Cancel pending creation", execute=self.cancel_pending_creation)],
            ),
            E2ERequestScenario(
                name="Nested creation preserves drafts and returns each result to its parent",
                user=self.admin_user,
                url=url,
                actions=[
                    E2EAction(name="Fill customer draft and open country", execute=self.open_country),
                    E2EAction(name="Fill country draft and open planet", execute=self.open_planet),
                    E2EAction(name="Validate inside the child only", execute=self.validate_planet),
                    E2EAction(name="Save planet into country", execute=self.save_planet),
                    E2EAction(name="Save country into original customer", execute=self.save_country),
                ],
            ),
            E2ERequestScenario(
                name="Escape closes only the child and restores parent focus and scroll lock",
                user=self.admin_user,
                url=url,
                actions=[
                    E2EAction(name="Open a country draft", execute=self.open_country),
                    E2EAction(name="Open nested planet", execute=self.open_planet),
                    E2EAction(name="Cancel and reopen nested creation", execute=self.cancel_and_reopen),
                    E2EAction(name="Cancel remaining parent", execute=self.cancel_country),
                ],
            ),
            E2ERequestScenario(
                name="TypeScript shell preserves Cotton slots and fullscreen behavior",
                user=self.admin_user,
                url=url,
                actions=[E2EAction(name="Exercise declarative shell", execute=self.check_shell)],
            ),
        ]

    def create_modals(self) -> Locator:
        """Select disposable creation dialogs in their creation order."""
        return self.page.locator('[data-modal-instance-of="create-object-modal"]')

    def open_country(self) -> None:
        """Keep a customer draft on the page and open its country creation dialog."""
        self.page.locator('#main-content input[name="first_name"]').fill("Draft customer")
        widget = self.page.locator('#main-content [data-field-name="country"][bloomerp-component="foreign-field-widget"]')
        widget.locator('input[type="text"]').focus()
        self.page.locator('.foreign-field-dropdown:visible [data-action="create-new"]').click()
        expect(self.create_modals()).to_have_count(1)
        expect(self.create_modals().locator('input[name="name"][required]')).to_be_visible()

    def open_planet(self) -> None:
        """Launch a second creation dialog from a populated country form."""
        country = self.create_modals().first
        country.locator('input[name="name"][required]').fill("Draft country")
        widget = country.locator('[data-field-name="planet"][bloomerp-component="foreign-field-widget"]')
        widget.locator('input[type="text"]').focus()
        self.page.locator('.foreign-field-dropdown:visible [data-action="create-new"]').click()
        expect(self.create_modals()).to_have_count(2)
        expect(self.create_modals().last.locator('input[name="name"][required]')).to_be_visible()
        expect(country.locator('input[name="name"][required]')).to_have_value("Draft country")
        expect(country).to_have_attribute("inert", "")
        child = self.create_modals().last
        child.locator('[data-modal-container]').focus()
        self.page.keyboard.press("Shift+Tab")
        self.assertTrue(child.evaluate("modal => modal.contains(document.activeElement)"))

    def validate_planet(self) -> None:
        """Submit an empty child form and verify only its body receives errors."""
        child = self.create_modals().last
        child.locator('input[name="name"][required]').fill("Clear before validation")
        child.locator('input[name="name"][required]').fill("")
        child.locator('form[hx-target="closest [data-modal-body]"]').evaluate("form => { form.noValidate = true; }")
        child.locator('#object-crud-container-save-button').click()
        expect(child.get_by_text("This field is required.", exact=True).first).to_be_visible()
        expect(self.create_modals()).to_have_count(2)
        expect(self.create_modals().first.locator('input[name="name"][required]')).to_have_value("Draft country")
        expect(self.page.locator('#main-content input[name="first_name"]')).to_have_value("Draft customer")

    def save_planet(self) -> None:
        """Persist a planet and verify its selection returns only to the country field."""
        child = self.create_modals().last
        child.locator('input[name="name"][required]').fill("Nested planet")
        self.page.keyboard.press("ControlOrMeta+s")
        expect(self.create_modals()).to_have_count(1)
        planet = self.PlanetModel.objects.get(name="Nested planet")
        country = self.create_modals().first
        expect(country.locator('input[name="planet"][data-generated="true"]')).to_have_value(str(planet.pk))
        expect(country.locator('input[name="name"][required]')).to_have_value("Draft country")

    def save_country(self) -> None:
        """Persist the parent modal and leave the original customer draft intact."""
        self.create_modals().first.locator('#object-crud-container-save-button').click()
        expect(self.create_modals()).to_have_count(0)
        country = self.CountryModel.objects.get(name="Draft country")
        expect(self.page.locator('#main-content input[name="country"][data-generated="true"]')).to_have_value(str(country.pk))
        expect(self.page.locator('#main-content input[name="first_name"]')).to_have_value("Draft customer")
        self.assertEqual(country.planet.name, "Nested planet")

    def cancel_and_reopen(self) -> None:
        """Check child cancellation, focus restoration, and fresh-instance reopening."""
        previous_id = self.create_modals().last.get_attribute("id")
        self.page.keyboard.press("Escape")
        expect(self.create_modals()).to_have_count(1)
        country = self.create_modals().first
        expect(country.locator('input[name="name"][required]')).to_have_value("Draft country")
        expect(country.locator('[data-field-name="planet"] input[type="text"]')).to_be_focused()
        self.assertEqual(self.page.locator('body').evaluate("body => body.style.overflow"), "hidden")
        self.open_planet()
        self.assertNotEqual(self.create_modals().last.get_attribute("id"), previous_id)
        self.page.keyboard.press("Escape")
        expect(self.create_modals()).to_have_count(1)

    def cancel_country(self) -> None:
        """Close the last modal and restore the original page's focus and scrolling."""
        self.create_modals().first.get_by_role('button', name="Close", exact=True).click()
        expect(self.create_modals()).to_have_count(0)
        expect(self.page.locator('#main-content input[name="first_name"]')).to_have_value("Draft customer")
        expect(self.page.locator('#main-content [data-field-name="country"] input[type="text"]')).to_be_focused()
        self.assertEqual(self.page.locator('body').evaluate("body => body.style.overflow"), "")

    def check_shell(self) -> None:
        """Verify slot nodes survive shell construction and controls fire only once."""
        self.page.evaluate("""() => {
            const declaration = document.createElement('div');
            declaration.id = 'shell-test-modal';
            declaration.setAttribute('bloomerp-component', 'modal');
            declaration.dataset.modalTitle = '<b>Literal title</b>';
            declaration.dataset.modalShowFooter = 'true';
            declaration.dataset.modalPadding = 'p-6';
            declaration.dataset.backdropClickClose = 'false';
            declaration.innerHTML = '<div data-modal-content><input value="original"></div><div data-modal-footer-content><button type="button">Footer action</button></div>';
            declaration.querySelector('input').value = 'preserved state';
            document.body.appendChild(declaration);
            document.body.dispatchEvent(new CustomEvent('htmx:load', {detail: {elt: declaration}}));
            declaration.__bloomerp_component.open();
        }""")
        modal = self.page.locator('#shell-test-modal')
        expect(modal.locator('input')).to_have_value("preserved state")
        expect(modal.locator('h3')).to_have_text("<b>Literal title</b>")
        expect(modal.get_by_role('button', name="Footer action")).to_be_visible()
        modal.get_by_role('button', name="Toggle fullscreen").click()
        expect(modal.locator('[data-modal-container]')).to_have_class(re.compile(r'\bh-full\b'))
        modal.get_by_role('button', name="Toggle fullscreen").click()
        self.assertNotIn('h-full', modal.locator('[data-modal-container]').get_attribute('class').split())
        self.assertIn('p-6', modal.locator('[data-modal-body]').get_attribute('class').split())
        modal.click(position={"x": 1, "y": 1})
        expect(modal).to_be_visible()
        modal.get_by_role('button', name="Close", exact=True).click()
        expect(modal).to_be_hidden()
        modal.evaluate("""parent => {
            parent.__bloomerp_component.setOpener(document.body);
            parent.__bloomerp_component.open();
            const child = document.createElement('div');
            child.id = 'reusable-child-modal';
            child.setAttribute('bloomerp-component', 'modal');
            document.body.appendChild(child);
            document.body.dispatchEvent(new CustomEvent('htmx:load', {detail: {elt: child}}));
            child.__bloomerp_component.setOpener(parent.querySelector('input'));
            child.__bloomerp_component.open();
            parent.__bloomerp_component.close();
        }""")
        reusable_child = self.page.locator('#reusable-child-modal')
        expect(modal).to_be_hidden()
        expect(reusable_child).to_be_hidden()
        reusable_child.evaluate("child => { child.__bloomerp_component.setOpener(document.body); child.__bloomerp_component.open(); }")
        expect(reusable_child).to_be_visible()
        reusable_child.get_by_role('button', name="Close", exact=True).click()
        expect(reusable_child).to_be_hidden()

    def defer_creation_request(self, route: Route) -> None:
        """Hold a form response until the test has cancelled its owning modal."""
        self.pending_creation_request = route

    def cancel_pending_creation(self) -> None:
        """Verify a late form response cannot resurrect a closed instance."""
        self.page.route('**/components/create-object/**', self.defer_creation_request)
        widget = self.page.locator('#main-content [data-field-name="country"][bloomerp-component="foreign-field-widget"]')
        widget.locator('input[type="text"]').focus()
        self.page.locator('.foreign-field-dropdown:visible [data-action="create-new"]').click()
        expect(self.create_modals().get_by_text('Loading…', exact=True)).to_be_visible()
        self.create_modals().get_by_role('button', name="Close", exact=True).click()
        expect(self.create_modals()).to_have_count(0)
        self.assertIsNotNone(self.pending_creation_request)
        self.pending_creation_request.fulfill(status=200, content_type='text/html', body='<p>Late response</p>')
        self.page.unroute('**/components/create-object/**')
        expect(self.create_modals()).to_have_count(0)
        expect(self.page.get_by_text('Late response', exact=True)).to_have_count(0)

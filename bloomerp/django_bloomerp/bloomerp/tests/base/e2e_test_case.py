from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.db.models import Model
from playwright.sync_api import expect

from bloomerp.tests.e2e.base import BaseE2ETestCase


E2ECallback = Callable[[], Any]
E2EValidator = Callable[[], bool | None]
DeferredUrl = str | Callable[[], str]


@dataclass
class E2EAction:
    """One deferred browser action and its optional assertions."""

    execute: E2ECallback
    validators: E2EValidator | list[E2EValidator] | None = None
    name: str | None = None


@dataclass
class E2ERequestSetup:
    """One declarative end-to-end browser scenario."""

    name: str
    actions: list[E2EAction]
    user: AbstractBaseUser | None = None
    url: DeferredUrl | None = None
    description: str | None = None
    prepare: E2ECallback | None = None
    cleanup: E2ECallback | None = None


class BloomerpE2ETestCase(BaseE2ETestCase):
    """Run declarative Playwright scenarios with common deferred actions."""

    def get_test_scenarios(self) -> list[E2ERequestSetup]:
        """Return the browser scenarios declared by the concrete test case."""
        return []

    def test_request_setups(self) -> None:
        """Execute each configured E2E scenario as an individual subtest."""
        for index, setup in enumerate(self.get_test_scenarios(), start=1):
            scenario_name = setup.name or f"E2E request setup {index}"
            with self.subTest(name=scenario_name):
                self._run_request_setup(setup, scenario_name)

    def _run_request_setup(
        self,
        setup: E2ERequestSetup,
        scenario_name: str,
    ) -> None:
        """Run one scenario in a fresh browser context."""
        self._reset_browser_context()
        try:
            if setup.prepare:
                setup.prepare()

            if setup.user is not None:
                self._authenticate_browser(setup.user)

            if setup.url is not None:
                self.goto(self._resolve_url(setup.url))

            for index, action in enumerate(setup.actions, start=1):
                action_name = action.name or f"action {index}"
                try:
                    action.execute()
                    self._run_action_validators(action)
                except Exception as exc:
                    raise AssertionError(
                        f"E2E action {action_name!r} failed in {scenario_name!r}: "
                        f"{setup.description or ''}"
                    ) from exc
        finally:
            if setup.cleanup:
                setup.cleanup()

    def _reset_browser_context(self) -> None:
        """Give every request setup independent cookies and browser storage."""
        current_context = getattr(self, "context", None)
        if current_context is not None:
            current_context.close()

        self.context = self._browser.new_context(
            **self.get_browser_context_options()
        )
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.default_timeout)
        self.page.set_default_navigation_timeout(self.default_timeout)

    def _authenticate_browser(self, user: AbstractBaseUser) -> None:
        """Authenticate the fresh browser context through Django's test session."""
        self.client.logout()
        self.client.force_login(user)
        session_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.context.add_cookies(
            [
                {
                    "name": settings.SESSION_COOKIE_NAME,
                    "value": session_cookie.value,
                    "url": self.live_server_url,
                }
            ]
        )

    def _run_action_validators(self, action: E2EAction) -> None:
        validators = action.validators
        if callable(validators):
            validators = [validators]

        for validator in validators or []:
            result = validator()
            if result is not None:
                self.assertTrue(result)

    @staticmethod
    def _resolve_url(url: DeferredUrl) -> str:
        return url() if callable(url) else url

    def go_to_page(self, url: DeferredUrl) -> E2ECallback:
        """Return an action that navigates to a URL when executed."""
        return lambda: self.goto(self._resolve_url(url))

    def input_field(self, field_id: str, value: str) -> E2ECallback:
        """Return an action that fills a Django form field by field ID."""
        return lambda: self.page.locator(f"#id_{field_id}").fill(value)

    def clear_field(self, field_id: str) -> E2ECallback:
        """Return an action that clears a Django form field by field ID."""
        return lambda: self.page.locator(f"#id_{field_id}").clear()

    def select_option(self, field_id: str, value: str) -> E2ECallback:
        """Return an action that selects a Django form option."""
        return lambda: self.page.locator(f"#id_{field_id}").select_option(value)

    def press_button(self, label: str, *, exact: bool = True) -> E2ECallback:
        """Return an action that presses a button by its accessible label."""
        return lambda: self.page.get_by_role(
            "button",
            name=label,
            exact=exact,
        ).click()

    def click(self, selector: str) -> E2ECallback:
        """Return an action that clicks a Playwright selector."""
        return lambda: self.page.locator(selector).click()

    def check(self, selector: str) -> E2ECallback:
        """Return an action that checks a matching control."""
        return lambda: self.page.locator(selector).check()

    def uncheck(self, selector: str) -> E2ECallback:
        """Return an action that unchecks a matching control."""
        return lambda: self.page.locator(selector).uncheck()

    def press_key(self, selector: str, key: str) -> E2ECallback:
        """Return an action that presses a key on a matching element."""
        return lambda: self.page.locator(selector).press(key)

    def upload_file(self, selector: str, path: str) -> E2ECallback:
        """Return an action that uploads a file through a matching input."""
        return lambda: self.page.locator(selector).set_input_files(path)

    def press_button_and_wait_for_response(
        self,
        label: str,
        path: DeferredUrl,
        *,
        method: str | None = None,
        expected_status: int | None = None,
        exact: bool = True,
    ) -> E2ECallback:
        """Return an action that presses a button and awaits its response."""

        def execute() -> None:
            with self.expect_response_for(
                self._resolve_url(path),
                method=method,
            ) as response_info:
                self.page.get_by_role(
                    "button",
                    name=label,
                    exact=exact,
                ).click()

            if expected_status is not None:
                self.assertEqual(response_info.value.status, expected_status)

        return execute

    def expect_visible(self, selector: str) -> E2EValidator:
        """Return an assertion that a selector is visible."""
        return lambda: expect(self.page.locator(selector)).to_be_visible()

    def expect_hidden(self, selector: str) -> E2EValidator:
        """Return an assertion that a selector is hidden."""
        return lambda: expect(self.page.locator(selector)).to_be_hidden()

    def expect_text(self, value: str, *, exact: bool = False) -> E2EValidator:
        """Return an assertion that visible page text is present."""
        return lambda: expect(
            self.page.get_by_text(value, exact=exact).first
        ).to_be_visible()

    def expect_field_value(self, field_id: str, value: str) -> E2EValidator:
        """Return an assertion for a Django form field's current value."""
        return lambda: expect(
            self.page.locator(f"#id_{field_id}")
        ).to_have_value(value)

    def expect_page_url(self, url: DeferredUrl) -> E2EValidator:
        """Return an assertion for the browser's current URL."""
        return lambda: expect(self.page).to_have_url(
            self.url(self._resolve_url(url))
        )

    def expect_database_value(
        self,
        instance: Model,
        field_name: str,
        expected_value: Any,
    ) -> E2EValidator:
        """Return an assertion that refreshes and checks one model field."""

        def validator() -> bool:
            instance.refresh_from_db()
            return getattr(instance, field_name) == expected_value

        return validator

    @staticmethod
    def custom_action(callback: E2ECallback) -> E2ECallback:
        """Use arbitrary deferred Playwright or application code as an action."""
        return callback

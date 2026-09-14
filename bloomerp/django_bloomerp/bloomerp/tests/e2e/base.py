from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Response,
    expect,
    sync_playwright,
)

from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels


class BaseE2ETestCase(BaseBloomerpTestCaseWithModels, StaticLiveServerTestCase):
    """Base class for stateful Bloomerp end-to-end tests.

    The class combines the standard Bloomerp test data with a static live
    server and an isolated Playwright browser context for every test. Subclasses
    therefore have access to ``CustomerModel``, ``admin_user``, ``normal_user``,
    ``page``, and ``live_server_url``.

    To record actions after arranging a test, put ``self.start_codegen()`` at
    the desired point and run that test with ``BLOOMERP_E2E_CODEGEN=1``. The
    method is intentionally a no-op without the environment variable, so the
    same test remains safe to run in the normal headless suite.

    When running through pytest, pass ``--headed`` to watch the browser and
    optionally ``--slowmo MILLISECONDS`` to delay each Playwright operation.
    """

    codegen_environment_variable = "BLOOMERP_E2E_CODEGEN"
    headed_environment_variable = "BLOOMERP_E2E_HEADED"
    slow_mo_environment_variable = "BLOOMERP_E2E_SLOW_MO"
    test_password = "testpass123"
    browser_name = "chromium"
    browser_launch_options: Mapping[str, Any] = {}
    browser_context_options: Mapping[str, Any] = {}
    default_timeout = 5_000

    _playwright: Playwright
    _browser: Browser
    _previous_async_unsafe: str | None
    context: BrowserContext
    page: Page

    @classmethod
    def codegen_enabled(cls) -> bool:
        value = os.environ.get(cls.codegen_environment_variable, "")
        return value.lower() in {"1", "true", "yes", "on"}

    @classmethod
    def get_browser_launch_options(cls) -> dict[str, Any]:
        """Return Playwright launch options, overridable by a subclass."""
        options = dict(cls.browser_launch_options)
        if cls.codegen_enabled() or os.environ.get(
            cls.headed_environment_variable
        ):
            options["headless"] = False
        else:
            options.setdefault("headless", True)

        slow_mo = os.environ.get(cls.slow_mo_environment_variable)
        if slow_mo:
            options["slow_mo"] = int(slow_mo)
        return options

    def get_browser_context_options(self) -> dict[str, Any]:
        """Return options for the fresh browser context created for a test."""
        return dict(self.browser_context_options)

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._previous_async_unsafe = os.environ.get("DJANGO_ALLOW_ASYNC_UNSAFE")
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
        try:
            cls._playwright = sync_playwright().start()
            browser_type = getattr(cls._playwright, cls.browser_name)
            cls._browser = browser_type.launch(**cls.get_browser_launch_options())
        except Exception:
            cls._restore_async_unsafe_setting()
            super().tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            browser = getattr(cls, "_browser", None)
            if browser is not None:
                browser.close()
        finally:
            try:
                playwright = getattr(cls, "_playwright", None)
                if playwright is not None:
                    playwright.stop()
            finally:
                cls._restore_async_unsafe_setting()
                super().tearDownClass()

    @classmethod
    def _restore_async_unsafe_setting(cls) -> None:
        previous = getattr(cls, "_previous_async_unsafe", None)
        if previous is None:
            os.environ.pop("DJANGO_ALLOW_ASYNC_UNSAFE", None)
        else:
            os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = previous

    def setUp(self) -> None:
        super().setUp()
        try:
            self._make_test_users_loginable()
            self.context = self._browser.new_context(
                **self.get_browser_context_options()
            )
            self.page = self.context.new_page()
            self.page.set_default_timeout(self.default_timeout)
            self.page.set_default_navigation_timeout(self.default_timeout)
            self.extendedE2ESetup()
        except Exception:
            context = getattr(self, "context", None)
            if context is not None:
                context.close()
            super().tearDown()
            raise

    def tearDown(self) -> None:
        try:
            context = getattr(self, "context", None)
            if context is not None:
                context.close()
                self.context = None  # type: ignore[assignment]
        finally:
            super().tearDown()

    def _make_test_users_loginable(self) -> None:
        """Give inherited test users a known plain-text E2E password."""
        if not self.auto_create_users:
            return

        for user in (self.admin_user, self.normal_user):
            user.set_password(self.test_password)
            user.save(update_fields=["password"])

    def extendedE2ESetup(self) -> None:
        """Hook for browser setup that must run after ``self.page`` exists."""

    def url(self, path: str = "/") -> str:
        """Return an absolute live-server URL for ``path``."""
        if path.startswith(("http://", "https://")):
            return path
        return f"{self.live_server_url.rstrip('/')}/{path.lstrip('/')}"

    def goto(self, path: str = "/", **kwargs: Any) -> Response | None:
        """Navigate to a path on the live test server."""
        kwargs.setdefault("wait_until", "domcontentloaded")
        return self.page.goto(self.url(path), **kwargs)

    def expect_response_for(
        self,
        path: str,
        *,
        method: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Wait for a response to a live-server path and optional HTTP method."""
        expected_path = urlsplit(self.url(path)).path
        expected_method = method.upper() if method else None

        def matches(response: Response) -> bool:
            return (
                urlsplit(response.url).path == expected_path
                and (
                    expected_method is None
                    or response.request.method == expected_method
                )
            )

        options = {"timeout": timeout} if timeout is not None else {}
        return self.page.expect_response(matches, **options)

    def login(
        self,
        user: AbstractBaseUser | str,
        password: str | None = None,
        *,
        expected_path: str = "/",
    ) -> Page:
        """Log in through the UI and wait for the expected destination."""
        username = user if isinstance(user, str) else user.get_username()
        self.goto("/login/")
        self.page.locator('input[name="username"]').fill(username)
        self.page.locator('input[name="password"]').fill(
            password or self.test_password
        )
        self.page.get_by_role("button", name="Login").click()
        expect(self.page).to_have_url(self.url(expected_path))
        return self.page
    
    def login_as_admin(self, *, expected_path: str = "/") -> Page:
        return self.login(self.admin_user, expected_path=expected_path)

    def login_as_normal_user(self, *, expected_path: str = "/") -> Page:
        return self.login(self.normal_user, expected_path=expected_path)

    def start_codegen(self) -> bool:
        """Open Playwright Inspector here when live code generation is enabled.

        Actions performed after the pause are rendered as Python code in the
        Inspector. Stop recording there and copy the generated steps into the
        test once the journey is complete.
        """
        if not self.codegen_enabled():
            return False

        self.page.pause()
        return True

    record_from_here = start_codegen

import os

import pytest
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def pytest_configure(config):
    """Apply pytest-playwright's CLI options to unittest-style E2E cases."""
    if config.getoption("--headed"):
        os.environ["BLOOMERP_E2E_HEADED"] = "1"
    else:
        os.environ.pop("BLOOMERP_E2E_HEADED", None)

    slow_mo = config.getoption("--slowmo")
    if slow_mo:
        os.environ["BLOOMERP_E2E_SLOW_MO"] = str(slow_mo)
    else:
        os.environ.pop("BLOOMERP_E2E_SLOW_MO", None)


@pytest.fixture(scope="class")
def live_server_url(request):
    """Provide live server URL to test class."""
    server = StaticLiveServerTestCase
    server.setUpClass()
    request.addfinalizer(server.tearDownClass)
    return server.live_server_url


@pytest.fixture(scope="function")
def page(browser):
    """Create a new page for each test."""
    page = browser.new_page()
    yield page
    page.close()


@pytest.fixture(scope="session")
def browser(browser_type_launch_args):
    """Create browser instance for test session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(**browser_type_launch_args)
        yield browser
        browser.close()


@pytest.fixture
def test_user(db):
    User = get_user_model()
    user = User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )
    return user


@pytest.fixture
def authenticated_page(page, live_server_url, test_user):
    page.goto(f"{live_server_url}/login/")
    page.locator('input[name="username"]').fill("testuser")
    page.locator('input[name="password"]').fill("testpass123")
    page.get_by_role("button", name="Login").click()
    page.wait_for_url(f"{live_server_url}/")
    return page

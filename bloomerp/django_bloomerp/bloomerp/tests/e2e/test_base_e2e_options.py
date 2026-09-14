import os


def _get_e2e_test_case():
    from bloomerp.tests.base import BloomerpE2ETestCase

    return BloomerpE2ETestCase


def test_pytest_cli_options_are_forwarded_to_the_e2e_launcher(pytestconfig):
    assert bool(os.environ.get("BLOOMERP_E2E_HEADED")) is pytestconfig.getoption(
        "--headed"
    )

    expected_slow_mo = pytestconfig.getoption("--slowmo")
    actual_slow_mo = os.environ.get("BLOOMERP_E2E_SLOW_MO")
    assert actual_slow_mo == (str(expected_slow_mo) if expected_slow_mo else None)


def test_pytest_browser_options_are_applied_to_e2e_test_cases(monkeypatch):
    e2e_test_case = _get_e2e_test_case()
    monkeypatch.delenv(
        e2e_test_case.codegen_environment_variable, raising=False
    )
    monkeypatch.setenv(e2e_test_case.headed_environment_variable, "1")
    monkeypatch.setenv(e2e_test_case.slow_mo_environment_variable, "250")
    monkeypatch.setattr(
        e2e_test_case,
        "browser_launch_options",
        {"channel": "chromium"},
    )

    assert e2e_test_case.get_browser_launch_options() == {
        "channel": "chromium",
        "headless": False,
        "slow_mo": 250,
    }


def test_e2e_test_cases_remain_headless_without_a_pytest_override(monkeypatch):
    e2e_test_case = _get_e2e_test_case()
    monkeypatch.delenv(
        e2e_test_case.codegen_environment_variable, raising=False
    )
    monkeypatch.delenv(
        e2e_test_case.headed_environment_variable, raising=False
    )
    monkeypatch.delenv(
        e2e_test_case.slow_mo_environment_variable, raising=False
    )
    monkeypatch.setattr(e2e_test_case, "browser_launch_options", {})

    assert e2e_test_case.get_browser_launch_options() == {"headless": True}

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.db.models import Model
from django.http import HttpResponse
from django.urls import reverse

from bloomerp.modules.definition import ModuleConfig


ResponseValidator = Callable[[HttpResponse], bool]
RequestPreparation = Callable[["RequestScenario"], None]


@dataclass
class ExpectedResult:
    """Expected response properties for one reusable request scenario."""

    status_code: int = 200
    response_validators: ResponseValidator | list[ResponseValidator] | None = None


@dataclass
class RequestScenario:
    """One request scenario executed by :class:`RequestTestCaseMixin`."""

    method: Literal[
        "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"
    ] = "GET"
    user: AbstractBaseUser | None = None
    expected: ExpectedResult = field(default_factory=ExpectedResult)
    name: str | None = None
    description: str | None = None
    data: dict | None = None
    query_params: dict | None = None
    view_kwargs: dict | None = None
    headers: dict | None = None
    content_type: str | None = None
    follow: bool = False
    view_name: str | None = None
    prepare: RequestPreparation | None = None


@dataclass(kw_only=True)
class ModelRequestScenario(RequestScenario):
    """A request scenario that overrides the test case's model route context."""

    model: type[Model]


@dataclass(kw_only=True)
class ModuleRequestScenario(RequestScenario):
    """A request scenario that overrides the test case's module route context."""

    module: ModuleConfig | str


class RequestTestCaseMixin:
    """Run declarative HTTP scenarios against a routed Bloomerp endpoint."""

    view_name: str | None = None

    def get_endpoint(
        self,
        view_name: str,
        kwargs: dict | None,
        setup: RequestScenario | None = None,
    ) -> str:
        """Resolve a scenario's endpoint."""
        return reverse(viewname=view_name, kwargs=kwargs)

    def get_test_scenarios(self) -> list[RequestScenario]:
        """Return the request scenarios defined by the concrete test case."""
        raise NotImplementedError("Request test cases must define request setups")

    def test_request_scenarios(self) -> None:
        """
        Use case: A view or component declares reusable request scenarios.
        Expected result: Every response matches its status and custom validators.
        """
        # 1. Do not execute the reusable base class itself.
        if self.view_name is None:
            return

        # 2. Execute every scenario against its selected route.
        for index, setup in enumerate(self.get_test_scenarios(), start=1):
            scenario_name = setup.name or f"request setup {index}"
            with self.subTest(name=scenario_name):
                self._run_request_scenario(setup, scenario_name)

    def _run_request_scenario(self, setup: RequestScenario, scenario_name: str) -> None:
        """Execute one isolated request scenario."""
        selected_view_name = setup.view_name or self.view_name
        with transaction.atomic():
            try:
                if setup.prepare:
                    setup.prepare(setup)

                if setup.user:
                    self.client.force_login(setup.user)
                else:
                    self.client.logout()

                request_kwargs = {
                    "path": self.get_endpoint(
                        selected_view_name,
                        setup.view_kwargs,
                        setup,
                    ),
                    "data": setup.data,
                    "query_params": setup.query_params,
                    "headers": setup.headers,
                    "follow": setup.follow,
                }
                if setup.content_type:
                    if setup.method in {"GET", "HEAD", "TRACE"}:
                        raise ValueError(
                            f"{setup.method} requests do not support content_type"
                        )
                    request_kwargs["content_type"] = setup.content_type

                response = getattr(self.client, setup.method.lower())(**request_kwargs)
                self.assertEqual(
                    response.status_code,
                    setup.expected.status_code,
                    f"Unexpected status code for {scenario_name}: "
                    f"{setup.description or ''}",
                )

                validators = setup.expected.response_validators
                if callable(validators):
                    validators = [validators]
                for validator in validators or []:
                    self.assertTrue(
                        validator(response),
                        f"Response validator {self._validator_name(validator)} "
                        f"failed for {scenario_name}: {setup.description or ''}",
                    )
            finally:
                self.client.logout()
                transaction.set_rollback(True)

    @staticmethod
    def _named_validator(name: str, validator: ResponseValidator) -> ResponseValidator:
        """Assign a descriptive name used in assertion failures."""
        validator.__name__ = name
        return validator

    @staticmethod
    def _validator_name(validator: ResponseValidator) -> str:
        """Return a readable validator name."""
        return getattr(validator, "__name__", type(validator).__name__)

    @classmethod
    def contains_text(cls, value: str) -> ResponseValidator:
        """Validate that a response contains text."""
        return cls._named_validator(
            f"contains_text({value!r})",
            lambda response: value in response.content.decode(response.charset or "utf-8"),
        )

    @classmethod
    def does_not_contain_text(cls, value: str) -> ResponseValidator:
        """Validate that a response does not contain text."""
        return cls._named_validator(
            f"does_not_contain_text({value!r})",
            lambda response: value
            not in response.content.decode(response.charset or "utf-8"),
        )

    @classmethod
    def contains_div(cls, value: str) -> ResponseValidator:
        """Validate that a response contains an expected div fragment."""
        return cls._named_validator(f"contains_div({value!r})", cls.contains_text(value))

    @classmethod
    def is_json(cls) -> ResponseValidator:
        """Validate that a response contains JSON."""

        def validator(response: HttpResponse) -> bool:
            try:
                response.json()
            except (TypeError, ValueError):
                return False
            return True

        return cls._named_validator("is_json()", validator)

    @classmethod
    def key_in_json(cls, key: str) -> ResponseValidator:
        """Validate that a top-level JSON key exists."""

        def validator(response: HttpResponse) -> bool:
            try:
                payload = response.json()
            except (TypeError, ValueError):
                return False
            return isinstance(payload, dict) and key in payload

        return cls._named_validator(f"key_in_json({key!r})", validator)

    @classmethod
    def json_exact(cls, expected_json: Any) -> ResponseValidator:
        """Validate an exact decoded JSON response."""

        def validator(response: HttpResponse) -> bool:
            try:
                return response.json() == expected_json
            except (TypeError, ValueError):
                return False

        return cls._named_validator(f"json_exact({expected_json!r})", validator)

    @classmethod
    def json_key_equals(cls, key: str, expected_value: Any) -> ResponseValidator:
        """Validate a top-level JSON value."""

        def validator(response: HttpResponse) -> bool:
            try:
                payload = response.json()
            except (TypeError, ValueError):
                return False
            return isinstance(payload, dict) and payload.get(key) == expected_value

        return cls._named_validator(
            f"json_key_equals({key!r}, {expected_value!r})", validator
        )

    @classmethod
    def header_equals(cls, name: str, expected_value: str) -> ResponseValidator:
        """Validate an exact response header."""
        return cls._named_validator(
            f"header_equals({name!r}, {expected_value!r})",
            lambda response: response.headers.get(name) == expected_value,
        )

    @classmethod
    def redirects_to(cls, url: str) -> ResponseValidator:
        """Validate a redirect target."""
        return cls._named_validator(
            f"redirects_to({url!r})",
            lambda response: response.status_code in {301, 302, 303, 307, 308}
            and response.headers.get("Location") == url,
        )

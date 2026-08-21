import ast
import re
from typing import Optional

from django.db import models
from django.db.models import QuerySet

from bloomerp.models.users.user import AbstractBloomerpUser
from bloomerp.permissions.definition import BloomerpPermission
from bloomerp.permissions.manager import UserPolicyManager


# TODO: opportunity to generalise resolvers in the future
class UserParameterResolver:
    parameter_name = "current_user"
    parameter_decorator = "{{}}"
    expression_pattern = re.compile(r"{{\s*(.*?)\s*}}")
    safe_zero_arg_methods = {
        "all",
        "first",
        "last",
        "none",
    }
    safe_query_methods = {
        "filter",
        "exclude",
        "order_by",
    }
    blocked_attribute_names = {
        "password",
    }

    def __init__(self, user: AbstractBloomerpUser, policy_manager: Optional[UserPolicyManager] = None):
        self.user = user
        self.policy_manager = policy_manager or UserPolicyManager(user)

    def resolve(self, query: str):
        if not isinstance(query, str):
            return query

        return self.expression_pattern.sub(
            lambda match: self._resolve_expression_match(match),
            query,
        )

    def _resolve_expression_match(self, match: re.Match) -> str:
        try:
            value = self._evaluate_expression(match.group(1))
        except Exception:
            return ""

        value = self._apply_permissions(value)
        return self._stringify_value(value)

    def _evaluate_expression(self, expression: str):
        segments = self._split_expression(expression)
        if not segments or segments[0] != self.parameter_name:
            return ""

        value = self.user
        for segment in segments[1:]:
            value = self._resolve_segment(value, segment)
        return value

    def _split_expression(self, expression: str) -> list[str]:
        segments = []
        current = []
        depth = 0
        quote = None
        escaped = False

        for char in expression.strip():
            if quote:
                current.append(char)
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue

            if char in {"'", '"'}:
                quote = char
                current.append(char)
                continue

            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth < 0:
                    raise ValueError("Invalid expression")
            elif char == "." and depth == 0:
                segments.append("".join(current).strip())
                current = []
                continue

            current.append(char)

        if quote or depth != 0:
            raise ValueError("Invalid expression")

        if current:
            segments.append("".join(current).strip())
        return segments

    def _resolve_segment(self, value, segment: str):
        name, args, kwargs, is_call = self._parse_segment(segment)
        if not self._is_safe_attribute_name(name):
            raise ValueError("Unsafe attribute")

        if isinstance(value, QuerySet) and name in {"first", "last"}:
            value = self._apply_permissions(value)

        attribute = getattr(value, name)
        if not callable(attribute):
            if is_call:
                raise ValueError("Attribute is not callable")
            return attribute

        if not self._is_safe_method(value, name):
            raise ValueError("Unsafe method")

        if not is_call and name in self.safe_zero_arg_methods:
            return attribute()

        if not is_call:
            return attribute

        if name in self.safe_zero_arg_methods and not args and not kwargs:
            return attribute()

        if name in self.safe_query_methods:
            return attribute(*args, **kwargs)

        raise ValueError("Unsafe method arguments")

    def _parse_segment(self, segment: str):
        name_match = re.fullmatch(r"([A-Za-z]\w*)(?:\((.*)\))?", segment)
        if not name_match:
            raise ValueError("Invalid expression segment")

        name = name_match.group(1)
        args_content = name_match.group(2)
        if args_content is None:
            return name, [], {}, False

        args, kwargs = self._parse_call_arguments(args_content)
        return name, args, kwargs, True

    def _parse_call_arguments(self, args_content: str) -> tuple[list, dict]:
        if not args_content.strip():
            return [], {}

        parsed = ast.parse(f"resolver({args_content})", mode="eval")
        call = parsed.body
        if not isinstance(call, ast.Call):
            raise ValueError("Invalid call")

        args = [ast.literal_eval(arg) for arg in call.args]
        kwargs = {}
        for keyword in call.keywords:
            if not keyword.arg:
                raise ValueError("Invalid call keyword")
            kwargs[keyword.arg] = ast.literal_eval(keyword.value)
        return args, kwargs

    def _is_safe_attribute_name(self, name: str) -> bool:
        return (
            bool(name)
            and not name.startswith("_")
            and name not in self.blocked_attribute_names
        )

    def _is_safe_method(self, value, name: str) -> bool:
        if name in self.safe_zero_arg_methods:
            return True
        if name in self.safe_query_methods:
            return isinstance(value, QuerySet) or hasattr(value, "get_queryset")
        return False

    def _apply_permissions(self, value):
        if value == self.user:
            return value

        if isinstance(value, QuerySet):
            allowed_queryset = self.policy_manager.get_queryset(value.model, BloomerpPermission.VIEW)
            return value.filter(pk__in=allowed_queryset.values_list("pk", flat=True))

        if isinstance(value, models.Model):
            if (
                self.policy_manager.get_queryset(value._meta.model, BloomerpPermission.VIEW)
                .filter(pk=value.pk)
                .exists()
            ):
                return value
            return ""

        return value

    def _stringify_value(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, QuerySet):
            return ",".join(str(pk) for pk in value.values_list("pk", flat=True))
        if isinstance(value, models.Model):
            return str(value.pk)
        return str(value)

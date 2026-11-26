from django.http import HttpRequest

from bloomerp.tokens import RequestToken, get_token, issue_token, request_token_id


class RequestTokenMixin:
    """Issue an optional context after a view has authorized its record."""

    request: HttpRequest

    def build_request_token(self) -> RequestToken | None:
        """Supply context for a new view when its subclass needs overrides."""
        return None

    def get_request_context_id(self) -> str | None:
        """Reuse the current context or make a newly issued context available during rendering."""
        if get_token(self.request) is not None:
            return request_token_id(self.request)
        token = self.build_request_token()
        if token is None:
            return None
        return issue_token(token, self.request, activate=True)
    

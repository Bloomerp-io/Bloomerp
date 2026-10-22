from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpRequest, JsonResponse

from bloomerp.router import router
from bloomerp.views.api.auth.common import (
    BaseSessionAuthApiView,
    find_existing_unique_field,
    get_login_credentials,
    get_registration_payload,
    json_not_found,
    parse_request_data,
    registration_endpoint_enabled,
    serialize_user,
)


@router.register(
    path="auth/register/",
    route_type="api",
    name="api_register",
)
class RegisterView(BaseSessionAuthApiView):
    def post(self, request: HttpRequest) -> JsonResponse:
        """Create an unprivileged account from validated public signup fields."""
        if not registration_endpoint_enabled():
            return json_not_found("Registration endpoints are disabled.")

        data = parse_request_data(request)
        if not isinstance(data, dict):
            return JsonResponse({"detail": "Registration data must be an object."}, status=400)
        password = data.get("password")
        password_confirmation = data.get("passwordConfirm", data.get("password_confirmation"))

        if not isinstance(password, str) or not password:
            return JsonResponse({"detail": "Password is required."}, status=400)

        if password_confirmation is not None and password != password_confirmation:
            return JsonResponse({"detail": "Passwords do not match."}, status=400)

        user_model = get_user_model()
        try:
            registration_data, missing_fields = get_registration_payload(data)
        except ValidationError as exc:
            return JsonResponse({"detail": " ".join(exc.messages)}, status=400)
        if missing_fields:
            field_list = ", ".join(missing_fields)
            return JsonResponse(
                {"detail": f"Missing required registration fields: {field_list}."},
                status=400,
            )

        for field_name, value in registration_data.items():
            existing_user = find_existing_unique_field(field_name, value)
            if existing_user is not None:
                return JsonResponse(
                    {"detail": f"An account with this {field_name} already exists."},
                    status=400,
                )

        registration_data.update(is_staff=False, is_superuser=False)
        try:
            validate_password(password, user=user_model(**registration_data))
        except ValidationError as exc:
            return JsonResponse({"detail": " ".join(exc.messages)}, status=400)

        try:
            user_model._default_manager.create_user(
                password=password,
                **registration_data,
            )
        except TypeError as exc:
            return JsonResponse(
                {"detail": f"Registration payload is incompatible with the configured user model: {exc}."},
                status=400,
            )
        except IntegrityError:
            return JsonResponse(
                {"detail": "Unable to create account with the provided credentials."},
                status=400,
            )

        credentials = get_login_credentials(data)
        user = authenticate(request, **credentials)
        if user is None:
            return JsonResponse(
                {"detail": "Account created, but automatic sign-in failed."},
                status=201,
            )

        login(request, user)
        return JsonResponse(
            {
                "authenticated": True,
                "user": serialize_user(user),
            },
            status=201,
        )

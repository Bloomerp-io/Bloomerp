from inspect import Parameter, signature

from django.contrib.auth import authenticate, get_user_model, login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db import router as database_router
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

        # Relation values arrive as IDs; only the manager should normalize them
        # for persistence. Use attnames on the unsaved password-validator user.
        validation_data = {
            user_model._meta.get_field(name).attname: value
            for name, value in registration_data.items()
        }
        try:
            validate_password(password, user=user_model(**validation_data))
        except ValidationError as exc:
            return JsonResponse({"detail": " ".join(exc.messages)}, status=400)

        manager = user_model._default_manager
        database = manager._db or database_router.db_for_write(user_model)
        create_user = manager.db_manager(database).create_user
        parameters = signature(create_user).parameters
        accepts_extra_fields = any(
            parameter.kind == Parameter.VAR_KEYWORD for parameter in parameters.values()
        )
        # Strict custom managers must not receive unsupported keyword arguments.
        for flag in ("is_staff", "is_superuser"):
            if accepts_extra_fields or flag in parameters:
                registration_data[flag] = False
        try:
            with transaction.atomic(using=database):
                created_user = create_user(password=password, **registration_data)
                if created_user.is_staff or created_user.is_superuser:
                    raise ValidationError("Public registration cannot create privileged accounts.")
        except ValidationError as exc:
            return JsonResponse({"detail": " ".join(exc.messages)}, status=400)
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

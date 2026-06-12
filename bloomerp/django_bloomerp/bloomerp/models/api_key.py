from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.http import HttpResponse
from django.utils import timezone

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from bloomerp.models.definition import ApiSettings, BloomerpModelConfig, DetailViewSettings, ModelViewSettings, ObjectAction
from bloomerp.modules.users import UsersModule
from django_htmx.http import HttpResponseClientRefresh

def revoke_api_key_action(request, api_key) -> HttpResponse:
    # TODO: Integrate with permissions
    from django.contrib import messages
    api_key.revoke()
    messages.success(request, "API key revoked successfully.")
    return HttpResponseClientRefresh()

class ApiKey(BloomerpModel):
    class Meta(BloomerpModel.Meta):
        db_table = "bloomerp_api_key"
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"
        indexes = [
            models.Index(fields=["key_prefix"], name="api_key_prefix_idx"),
            models.Index(fields=["account", "revoked_at"], name="api_key_account_active_idx"),
        ]
    
    TOKEN_PREFIX = "blp_live"
    PREFIX_LENGTH = 12

    bloomerp_config = BloomerpModelConfig(
        module=UsersModule,
        # is_internal=True,
        api_settings=ApiSettings(enable_auto_generation=False),
        object_actions=[
            ObjectAction(
                id="revoke_api_key",
                label="Revoke API Key",
                icon="fa fa-solid fa-xmark",
                execution_func=revoke_api_key_action,
                should_render_func=lambda request, obj: obj.is_usable
            )
        ],
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    title="API Key Details",
                    items=[
                        LayoutItem(id="account"),
                        LayoutItem(id="name"),
                        LayoutItem(id="is_usable"),
                        LayoutItem(id="last_used_at"),
                        LayoutItem(id="expires_at"),
                        LayoutItem(id="revoked_at"),
                    ]
                )
            ]
        ),
        detail_view_settings=DetailViewSettings(
            skip_views=[
                "document_templates",
                "files"
            ]
        ),
        model_view_settings=ModelViewSettings(
            skip_views=[
                
            ]
        )
    )

    avatar = None
    
    account = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="api_keys",
        help_text="The account whose permissions this API key uses.",
    )
    name = models.CharField(
        max_length=150,
        help_text="A human-readable label for this API key.",
    )
    key_prefix = models.CharField(
        max_length=32,
        editable=False,
        help_text="Visible token prefix used to identify the API key without storing the raw token.",
    )
    key_hash = models.CharField(
        max_length=255,
        editable=False,
        help_text="Hashed API key secret. The raw token is only shown when it is created.",
    )
    last_used_at = models.DateTimeField(
        null=True, 
        blank=True, 
        editable=False
    )
    expires_at = models.DateTimeField(
        null=True, 
        blank=True
    )
    revoked_at = models.DateTimeField(
        null=True, 
        blank=True, 
        editable=False
    )


    def __str__(self) -> str:
        return f"{self.name} ({self.key_prefix})"

    @property
    def is_revoked(self) -> bool:
        """Whether the key is revoked

        Returns:
            bool: True if the key is revoked, False otherwise
        """
        return self.revoked_at is not None

    @property
    def is_expired(self) -> bool:
        """Whether the key is expired

        Returns:
            bool: True if the key is expired, False otherwise
        """
        return self.expires_at is not None and self.expires_at <= timezone.now()

    @property
    def is_usable(self) -> bool:
        """Whether the key is usable

        Returns:
            bool: True if the key is usable, False otherwise
        """
        return not self.is_revoked and not self.is_expired

    @classmethod
    def generate_token(cls) -> tuple[str, str]:
        """Generates a new API token and its corresponding key prefix.
        Returns:
            tuple[str, str]: A tuple containing the key prefix and the full API token.
        """
        key_prefix = secrets.token_hex(cls.PREFIX_LENGTH // 2)
        secret = secrets.token_urlsafe(32)
        return key_prefix, f"{cls.TOKEN_PREFIX}_{key_prefix}_{secret}"

    def set_token(self, raw_token: str | None = None) -> str:
        """Set's the API token for the key.

        Args:
            raw_token (str | None, optional): The raw API token to set. If None, a new token is generated. Defaults to None.

        Returns:
            str: The raw API token.
        """
        if raw_token is None:
            self.key_prefix, raw_token = self.generate_token()
        else:
            self.key_prefix = self.extract_key_prefix(raw_token)

        self.key_hash = make_password(raw_token)
        return raw_token

    def check_token(self, raw_token: str) -> bool:
        return self.is_usable and check_password(raw_token, self.key_hash)

    def revoke(self, save: bool = True) -> None:
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            if save:
                self.save(update_fields=["revoked_at", "datetime_updated"])

    def mark_used(self, save: bool = True) -> None:
        self.last_used_at = timezone.now()
        if save:
            self.save(update_fields=["last_used_at", "datetime_updated"])

    @classmethod
    def extract_key_prefix(cls, raw_token: str) -> str:
        parts = str(raw_token or "").split("_", 3)
        token_prefix_parts = cls.TOKEN_PREFIX.split("_", 1)
        if len(parts) >= 4 and parts[:2] == token_prefix_parts:
            return parts[2]
        return ""

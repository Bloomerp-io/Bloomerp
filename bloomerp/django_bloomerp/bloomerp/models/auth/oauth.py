"""Persist authorization codes and access tokens for Bloomerp OAuth."""

from django.conf import settings
from django.db import models


class OAuthAuthorizationCode(models.Model):
    """Store a short-lived, single-use authorization code for PKCE exchange."""

    code_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    client_id = models.TextField()
    redirect_uri = models.TextField()
    resource = models.TextField()
    scope = models.CharField(max_length=200)
    code_challenge = models.CharField(max_length=128)
    expires_at = models.DateTimeField()


class OAuthAccessToken(models.Model):
    """Store only a digest of an OAuth bearer token."""

    token_hash = models.CharField(max_length=64, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    client_id = models.TextField()
    resource = models.TextField()
    scope = models.CharField(max_length=200)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

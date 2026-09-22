"""Synchronize declarative model policies with stored access control policies."""

import hashlib
import json
from collections.abc import Iterable

from django.apps import apps
from django.db import models, transaction

from bloomerp.models.access_control.policy import Policy
from bloomerp.models.definition import BloomerpModelConfig, DefaultPolicy
from bloomerp.permissions.manager import PolicyManager, ensure_model_permissions


def _policy_hash(declaration: DefaultPolicy) -> str:
    """Return a stable digest of the access rule that requires a database rebuild."""
    payload = json.dumps(
        declaration.access_rule.model_dump(mode="json"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sync_default_policies(
    model_classes: Iterable[type[models.Model]] | None = None,
) -> dict[str, Policy]:
    """Create or update declared policies, retaining IDs and user assignments."""
    synchronized: dict[str, Policy] = {}
    models_to_scan = model_classes if model_classes is not None else apps.get_models()

    with transaction.atomic():
        for model in models_to_scan:
            config = getattr(model, "bloomerp_config", None)
            if not isinstance(config, BloomerpModelConfig):
                continue
            declarations = config.permission_settings.default_policies
            if not declarations:
                continue

            ensure_model_permissions(model)
            for declaration in declarations:
                key = f"{model._meta.label_lower}:{declaration.id}"
                if len(key) > 512:
                    raise ValueError(f"Default policy key is too long: {key}")
                digest = _policy_hash(declaration)
                existing = Policy.objects.select_for_update().filter(
                    default_policy_key=key,
                ).first()

                if existing is None:
                    policy = PolicyManager.create_policy(model, declaration.access_rule)
                    policy.default_policy_key = key
                    policy.default_policy_hash = digest
                    policy.system_created = True
                elif existing.default_policy_hash != digest:
                    replacement = PolicyManager.create_policy(model, declaration.access_rule)
                    old_row_policy = existing.row_policy
                    old_field_policy = existing.field_policy
                    permission_ids = list(
                        replacement.global_permissions.values_list("pk", flat=True)
                    )
                    existing.row_policy = replacement.row_policy
                    existing.field_policy = replacement.field_policy
                    existing.save(update_fields=["row_policy", "field_policy"])
                    existing.global_permissions.set(permission_ids)
                    replacement.delete()
                    if not old_row_policy.policies.exists():
                        old_row_policy.delete()
                    if not old_field_policy.policies.exists():
                        old_field_policy.delete()
                    policy = existing
                    policy.default_policy_hash = digest
                else:
                    policy = existing

                policy.name = declaration.name
                policy.description = declaration.description
                policy.save()
                synchronized[key] = policy

    return synchronized

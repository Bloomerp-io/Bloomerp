"""Database phone-field fixtures for provider selection and permission scenarios."""

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Permission
from django.db import models
from bloomerp.model_fields.phone_number_field import PhoneNumberField
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.tests.models.communication.voip.fixtures import VoIPFixtures
from bloomerp.permissions.manager import PolicyManager
from bloomerp.permissions.definition import RowPolicyRuleContent
from bloomerp.tests.base import RequestScenario


def contact_label(obj: models.Model) -> str:
    """Expose a contact label through the standard object string representation."""
    return obj.name


class PhoneDirectoryFixtures(VoIPFixtures):
    """Provide real registered phone fields and separately granted row/field access."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create the phone-bearing model before transaction-scoped request scenarios."""
        super().setUpClass()
        cls.PhoneContact = create_test_models(
            "bloomerp",
            {
                "VoIPTestContact": {
                    "name": models.CharField(max_length=100),
                    "phone": PhoneNumberField(),
                    "__str__": contact_label,
                }
            },
            use_bloomerp_base=True,
        )["VoIPTestContact"]

    def phone_setup(self, scenario: RequestScenario | None = None) -> None:
        """Grant readable phone fields while withholding the label field itself."""
        self.prepare_voip()
        self.contact = self.PhoneContact.objects.create(
            name="Phone directory contact", phone="+32470000003"
        )
        content_type = ContentType.objects.get_for_model(self.PhoneContact)
        ApplicationField.objects.get_or_create(
            content_type=content_type,
            field="phone",
            defaults={"field_type": "PhoneNumberField"},
        )
        Permission.objects.get_or_create(
            content_type=content_type,
            codename="view_voiptestcontact",
            defaults={"name": "View phone contact"},
        )
        policy = PolicyManager.create_policy(
            self.PhoneContact,
            field_permissions={"phone": ["view"]},
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["view"], conditions=[], connector="AND"
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)

    def choose_phone(self, scenario: RequestScenario) -> None:
        """Select a signed directory result without introducing an IM connection."""
        from bloomerp.communication.builtins.instant_messaging.builtins.phone import (
            phone_recipients,
        )

        self.phone_setup()
        option = phone_recipients(
            self.normal_user, {}, "Phone directory contact", ""
        ).items[0]
        scenario.data = {"provider": "phone", "recipient_id": option.value}

    def choose_changed_phone(self, scenario: RequestScenario) -> None:
        """Change the source field after discovery to reject stale recipient selections."""
        self.choose_phone(scenario)
        self.contact.phone = "+32470000004"
        self.contact.save()

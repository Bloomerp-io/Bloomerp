"""Preserve cached mailbox names while adding configurable presentation and roles."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
import bloomerp.communication.builtins.emails.mailboxes


def forwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Convert cached lists to mappings without contacting mail providers."""
    account_model = apps.get_model("bloomerp", "EmailAccount")
    for account in account_model.objects.using(
        schema_editor.connection.alias
    ).iterator():
        if not isinstance(account.mailboxes, list):
            continue
        names = account.mailboxes
        main = next((name for name in names if name.casefold() == "inbox"), None)
        main = main or next(
            (name for name in names if "inbox" in name.casefold()), None
        )
        sent = next(
            (
                name
                for name in names
                if name.casefold() in {"sent", "sent items", "sent mail"}
            ),
            None,
        )
        sent = sent or next((name for name in names if "sent" in name.casefold()), None)
        account.mailboxes = {
            name: {
                "label": name,
                "main_folder": name == main,
                "sent_folder": name == sent,
                "color": "",
            }
            for name in names
        }
        account.save(update_fields=["mailboxes"])


def backwards(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Restore mailbox names when reverting the mapping schema."""
    account_model = apps.get_model("bloomerp", "EmailAccount")
    for account in account_model.objects.using(
        schema_editor.connection.alias
    ).iterator():
        if isinstance(account.mailboxes, dict):
            account.mailboxes = list(account.mailboxes)
            account.save(update_fields=["mailboxes"])


class Migration(migrations.Migration):
    dependencies = [("bloomerp", "0084_emailaccount_smtp_envelope_sender")]
    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="emailaccount",
            name="mailboxes",
            field=models.JSONField(
                blank=True,
                default=dict,
                validators=[bloomerp.communication.builtins.emails.mailboxes.validate_mailboxes],
                help_text="Provider mailbox names mapped to labels, roles and optional icon colors.",
                verbose_name="Mailboxes",
            ),
        ),
    ]

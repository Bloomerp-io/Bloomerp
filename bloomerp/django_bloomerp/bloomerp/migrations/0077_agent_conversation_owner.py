"""Retain conversation ownership while replacing the legacy history layout."""

from django.db import migrations


class Migration(migrations.Migration):
    """Rename the existing owner column before adding normalized agent tables."""

    dependencies = [("bloomerp", "0076_emailaccount_save_sent_emails")]
    operations = [
        migrations.RenameField(
            model_name="aiconversation", old_name="user", new_name="owner"
        )
    ]

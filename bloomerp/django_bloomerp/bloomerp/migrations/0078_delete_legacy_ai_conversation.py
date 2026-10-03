"""Remove the obsolete conversation table before creating normalized agent models."""

from django.db import migrations


class Migration(migrations.Migration):
    """Discard legacy conversations so the replacement needs no owner backfill."""

    dependencies = [("bloomerp", "0077_file_field_references")]

    operations = [migrations.DeleteModel(name="AIConversation")]

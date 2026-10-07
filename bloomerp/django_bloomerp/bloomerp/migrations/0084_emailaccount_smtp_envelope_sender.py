from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bloomerp", "0083_alter_fileextraction_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="emailaccount",
            name="smtp_envelope_sender",
            field=models.EmailField(
                blank=True,
                default="",
                max_length=255,
                verbose_name="SMTP envelope sender",
                help_text=(
                    "Leave blank to use the email address. For aliases, enter the primary "
                    "mailbox address if your provider requires it. Replies still go to the "
                    "visible sender unless a reply address is specified."
                ),
            ),
        ),
    ]

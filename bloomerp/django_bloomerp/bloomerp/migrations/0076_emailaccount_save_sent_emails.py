from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("bloomerp", "0075_alter_todo_assigned_to_alter_todo_requested_by")]

    operations = [
        migrations.AddField(
            model_name="emailaccount",
            name="save_sent_emails",
            field=models.BooleanField(
                default=False,
                verbose_name="Save sent emails via IMAP",
                help_text="Save a copy in the server's Sent folder after sending. Enable for providers "
                "such as Neo; leave disabled if your provider already saves sent emails automatically.",
            ),
        ),
    ]

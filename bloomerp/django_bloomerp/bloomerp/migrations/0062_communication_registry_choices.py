from django.db import migrations, models

import bloomerp.communication.builtins.emails.registry
import bloomerp.communication.registry


class Migration(migrations.Migration):
    dependencies = [("bloomerp", "0061_applicationfield_registry_choices")]

    operations = [
        migrations.AlterField(
            model_name="emailaccount",
            name="provider",
            field=models.CharField(
                choices=bloomerp.communication.builtins.emails.registry.email_provider_choices,
                default="imap",
                max_length=32,
                verbose_name="Provider",
            ),
        ),
        migrations.AlterField(
            model_name="inboxfolder",
            name="type",
            field=models.CharField(
                choices=bloomerp.communication.registry.inbox_folder_choices,
                max_length=50,
                verbose_name="Type",
            ),
        ),
        migrations.AlterField(
            model_name="inboxitem",
            name="item_type",
            field=models.CharField(
                choices=bloomerp.communication.registry.inbox_item_type_choices,
                max_length=50,
                verbose_name="Item Type",
            ),
        ),
    ]

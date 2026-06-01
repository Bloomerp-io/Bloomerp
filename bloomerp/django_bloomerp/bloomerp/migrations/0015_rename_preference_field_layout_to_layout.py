from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bloomerp", "0014_alter_applicationfield_field_type"),
    ]

    operations = [
        migrations.RenameField(
            model_name="usercreateviewpreference",
            old_name="field_layout",
            new_name="layout",
        ),
        migrations.RenameField(
            model_name="userdetailviewpreference",
            old_name="field_layout",
            new_name="layout",
        ),
        migrations.AlterField(
            model_name="usercreateviewpreference",
            name="layout",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterField(
            model_name="userdetailviewpreference",
            name="layout",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

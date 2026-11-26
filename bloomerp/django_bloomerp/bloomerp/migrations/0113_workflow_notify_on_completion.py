from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bloomerp', '0112_tutorial_double_click'),
    ]

    operations = [
        migrations.AddField(
            model_name='workflow',
            name='notify_on_completion',
            field=models.BooleanField(default=False, help_text='Send the workflow creator an inbox notification when a run succeeds or fails.', verbose_name='Notify on completion'),
        ),
    ]

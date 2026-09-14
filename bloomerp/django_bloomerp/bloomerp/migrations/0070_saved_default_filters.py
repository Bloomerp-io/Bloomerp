from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('bloomerp', '0069_saved_filter')]

    operations = [
        migrations.RemoveField(model_name='userlistviewpreference', name='default_filters'),
        migrations.AddField(
            model_name='userlistviewpreference', name='default_filters',
            field=models.ManyToManyField(blank=True, related_name='%(class)s_defaults', to='bloomerp.savedfilter', verbose_name='Default Filters'),
        ),
        migrations.AddField(
            model_name='workspace', name='default_filters',
            field=models.ManyToManyField(blank=True, related_name='%(class)s_defaults', to='bloomerp.savedfilter', verbose_name='Default Filters'),
        ),
    ]

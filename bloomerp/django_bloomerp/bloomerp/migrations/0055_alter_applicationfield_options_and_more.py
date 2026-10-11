import bloomerp.model_fields.code_field
import bloomerp.model_fields.icon_field
import bloomerp.model_fields.text_editor_field
import bloomerp.model_fields.user_field
import bloomerp.files.legacy_migrations
import bloomerp.models.users.user_list_view_preference
import bloomerp.models.workspaces.tile
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('bloomerp', '0054_user_detail_sidebar_view_preference'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='applicationfield',
            options={'managed': True, 'verbose_name': 'Application Field', 'verbose_name_plural': 'Application Fields'},
        ),
        migrations.AlterModelOptions(
            name='bookmark',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Bookmark', 'verbose_name_plural': 'Bookmarks'},
        ),
        migrations.AlterModelOptions(
            name='comment',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Comment', 'verbose_name_plural': 'Comments'},
        ),
        migrations.AlterModelOptions(
            name='documenttemplate',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Document Template', 'verbose_name_plural': 'Document Templates'},
        ),
        migrations.AlterModelOptions(
            name='documenttemplateheader',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Document Template Header', 'verbose_name_plural': 'Document Template Headers'},
        ),
        migrations.AlterModelOptions(
            name='documenttemplatestyling',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Document Template Styling', 'verbose_name_plural': 'Document Template Stylings'},
        ),
        migrations.AlterModelOptions(
            name='file',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'File', 'verbose_name_plural': 'Files'},
        ),
        migrations.AlterModelOptions(
            name='filefolder',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'File Folder', 'verbose_name_plural': 'File Folders'},
        ),
        migrations.AlterModelOptions(
            name='form',
            options={'verbose_name': 'Form', 'verbose_name_plural': 'Forms'},
        ),
        migrations.AlterModelOptions(
            name='formsubmission',
            options={'verbose_name': 'Form Submission', 'verbose_name_plural': 'Form Submissions'},
        ),
        migrations.AlterModelOptions(
            name='inbox',
            options={'verbose_name': 'Inbox', 'verbose_name_plural': 'Inboxes'},
        ),
        migrations.AlterModelOptions(
            name='initiative',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Initiative', 'verbose_name_plural': 'Initiatives'},
        ),
        migrations.AlterModelOptions(
            name='rowpolicyrulepermission',
            options={'managed': True, 'verbose_name': 'Row Policy Rule Permission', 'verbose_name_plural': 'Row Policy Rule Permissions'},
        ),
        migrations.AlterModelOptions(
            name='sidebar',
            options={'verbose_name': 'Sidebar', 'verbose_name_plural': 'Sidebars'},
        ),
        migrations.AlterModelOptions(
            name='sidebaritem',
            options={'verbose_name': 'Sidebar Item', 'verbose_name_plural': 'Sidebar Items'},
        ),
        migrations.AlterModelOptions(
            name='tile',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Tile', 'verbose_name_plural': 'Tiles'},
        ),
        migrations.AlterModelOptions(
            name='todo',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Todo', 'verbose_name_plural': 'Todos'},
        ),
        migrations.AlterModelOptions(
            name='todolabel',
            options={'managed': True, 'verbose_name': 'Todo Label', 'verbose_name_plural': 'Todo Labels'},
        ),
        migrations.AlterModelOptions(
            name='user',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'verbose_name': 'User', 'verbose_name_plural': 'Users'},
        ),
        migrations.AlterModelOptions(
            name='userdetailviewtabitem',
            options={'ordering': ['position', 'id'], 'verbose_name': 'User Detail View Tab Item', 'verbose_name_plural': 'User Detail View Tab Items'},
        ),
        migrations.AlterModelOptions(
            name='userdetailviewtabspreference',
            options={'verbose_name': 'User Detail View Tabs Preference', 'verbose_name_plural': 'User Detail View Tabs Preferences'},
        ),
        migrations.AlterModelOptions(
            name='userlistviewpreference',
            options={'verbose_name': 'User List View Preference', 'verbose_name_plural': 'User List View Preferences'},
        ),
        migrations.AlterModelOptions(
            name='workspace',
            options={'default_permissions': ('add', 'change', 'delete', 'view', 'export', 'import', 'bulk_change', 'bulk_delete'), 'managed': True, 'verbose_name': 'Workspace', 'verbose_name_plural': 'Workspaces'},
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='action',
            field=models.CharField(choices=[('CHANGE', 'Change'), ('CREATE', 'Create'), ('DELETE', 'Delete')], default='CHANGE', max_length=12, verbose_name='Action'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='actor',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL, verbose_name='Actor'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='is_create',
            field=models.BooleanField(default=False, verbose_name='Is Create'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='object_id',
            field=models.CharField(max_length=255, verbose_name='Object ID'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='payload',
            field=models.JSONField(blank=True, null=True, verbose_name='Payload'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='source',
            field=models.CharField(choices=[('DETAIL', 'Detail'), ('API', 'API'), ('CREATE', 'Create'), ('BULK', 'Bulk')], default='DETAIL', max_length=12, verbose_name='Source'),
        ),
        migrations.AlterField(
            model_name='activitylog',
            name='timestamp',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Timestamp'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='args',
            field=models.JSONField(blank=True, help_text='Extra arguments for the conversation', null=True, verbose_name='Args'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='auto_named',
            field=models.BooleanField(default=False, help_text='Whether the conversation has been auto-named', verbose_name='Auto Named'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='conversation_history',
            field=models.JSONField(blank=True, null=True, verbose_name='Conversation History'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='conversation_type',
            field=models.CharField(choices=[('sql', 'SQL'), ('document_template', 'Document Template Generator'), ('tiny_mce_content', 'TinyMCE Content Generator'), ('bloom_ai', 'Bloom AI'), ('code', 'Code Generator'), ('object_bloom_ai', 'Object Bloom AI')], default='bloom_ai', max_length=20, verbose_name='Conversation Type'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='title',
            field=models.CharField(default='AI Conversation', max_length=255, verbose_name='Title'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='aiconversation',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='account',
            field=models.ForeignKey(help_text='The account whose permissions this API key uses.', on_delete=django.db.models.deletion.CASCADE, related_name='api_keys', to=settings.AUTH_USER_MODEL, verbose_name='Account'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Expires At'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='key_hash',
            field=models.CharField(editable=False, help_text='Hashed API key secret. The raw token is only shown when it is created.', max_length=255, verbose_name='Key Hash'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='key_prefix',
            field=models.CharField(editable=False, help_text='Visible token prefix used to identify the API key without storing the raw token.', max_length=32, verbose_name='Key Prefix'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='last_used_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Last Used At'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='name',
            field=models.CharField(help_text='A human-readable label for this API key.', max_length=150, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='revoked_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Revoked At'),
        ),
        migrations.AlterField(
            model_name='apikey',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='content_type',
            field=models.ForeignKey(help_text='The content type (model) this field belongs to.', on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='db_column',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='DB Column'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='db_field_type',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='DB Field Type'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='db_table',
            field=models.CharField(blank=True, help_text='The database table this field belongs to.', max_length=100, null=True, verbose_name='DB Table'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='field',
            field=models.CharField(help_text='The name of the field.', max_length=100, verbose_name='Field'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='field_type',
            field=models.CharField(choices=[('Property', 'Property'), ('AutoField', 'Auto Field'), ('BigAutoField', 'Big Auto Field'), ('SmallAutoField', 'Small Auto Field'), ('CharField', 'Char Field'), ('CodeField', 'Code Field'), ('ChoiceField', 'Choice Field'), ('TextField', 'Text Field'), ('EmailField', 'Email Field'), ('URLField', 'URL Field'), ('AddressField', 'Address Field'), ('PhoneNumberField', 'Phone Number Field'), ('SlugField', 'Slug Field'), ('IntegerField', 'Integer Field'), ('FloatField', 'Float Field'), ('DecimalField', 'Decimal Field'), ('PositiveIntegerField', 'Positive Integer Field'), ('PositiveSmallIntegerField', 'Positive Small Integer Field'), ('BigIntegerField', 'Big Integer Field'), ('SmallIntegerField', 'Small Integer Field'), ('BooleanField', 'Boolean Field'), ('NullBooleanField', 'Null Boolean Field'), ('DateField', 'Date Field'), ('WeekField', 'Week Field'), ('DateTimeField', 'DateTime Field'), ('TimeField', 'Time Field'), ('DurationField', 'Duration Field'), ('FileField', 'File Field'), ('ImageField', 'Image Field'), ('ForeignKey', 'Foreign Key'), ('OneToOneField', 'One To One Field'), ('ManyToManyField', 'Many To Many Field'), ('OneToManyField', 'One To Many Field'), ('UserField', 'User Field'), ('OneToOneUserField', 'One To One User Field'), ('UUIDField', 'UUID Field'), ('BinaryField', 'Binary Field'), ('IPAddressField', 'IP Address Field'), ('GenericIPAddressField', 'Generic IP Address Field'), ('JSONField', 'JSON Field'), ('ArrayField', 'Array Field'), ('HStoreField', 'HStore Field'), ('GenericRelation', 'Generic Relation'), ('GenericForeignKey', 'Generic Foreign Key'), ('StatusField', 'Status Field'), ('IconField', 'Icon Field'), ('BloomerpFileField', 'Bloomerp File Field'), ('FilesRelationField', 'Files')], help_text='The type of the field.', max_length=100, verbose_name='Field Type'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='meta',
            field=models.JSONField(blank=True, help_text='Additional metadata about the field.', null=True, verbose_name='Meta'),
        ),
        migrations.AlterField(
            model_name='applicationfield',
            name='related_model',
            field=models.ForeignKey(blank=True, help_text='Related model for ForeignKey, OneToOneField, ManyToManyField', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='related_models', to='contenttypes.contenttype', verbose_name='Related Model'),
        ),
        migrations.AlterField(
            model_name='bookmark',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='bookmark',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='bookmark',
            name='object_id',
            field=models.CharField(max_length=255, verbose_name='Object ID'),
        ),
        migrations.AlterField(
            model_name='bookmark',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='content',
            field=models.TextField(verbose_name='Content'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='object_id',
            field=models.CharField(help_text='In order to support both UUID and integer primary keys', max_length=36, verbose_name='Object ID'),
        ),
        migrations.AlterField(
            model_name='comment',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='content_types',
            field=models.ManyToManyField(blank=True, help_text='Root object types that can be used as variables in the document template.', related_name='document_templates', to='contenttypes.contenttype', verbose_name='Content Types'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='custom_styling',
            field=bloomerp.model_fields.code_field.CodeField(blank=True, default='\np {\n    font-size: 11pt;\n    line-height: 1.5;\n    margin: 0 0 8pt 0;\n}\np:last-child {\n    margin-bottom: 0;\n}\nh1 {\n    font-size: 24px;\n    font-weight: bold;\n}\nh2 {\n    font-size: 20px;\n    font-weight: bold;\n}\nh3 {\n    font-size: 18px;\n    font-weight: bold;\n}\nul {\n    list-style-type: disc;\n    margin-left: 20px;\n}\nol {\n    list-style-type: decimal;\n    margin-left: 20px;\n}\ntable {\n    border-collapse: collapse;\n    width: 100%;\n}\nth, td {\n    border: 1px solid black;\n    padding: 8px;\n    text-align: left;\n}\n\n', help_text='Custom CSS styling for the document template.', language='css', verbose_name='Custom Styling'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='footer',
            field=models.TextField(blank=True, help_text='Footer content of the document template.', null=True, verbose_name='Footer'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='free_variables',
            field=models.JSONField(blank=True, default=list, verbose_name='Free Variables'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='include_page_numbers',
            field=models.BooleanField(default=True, help_text='Signifies whether the page numbers are included or not.', verbose_name='Include Page Numbers'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='name',
            field=models.CharField(help_text='Name of the document template.', max_length=100, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='page_margin',
            field=models.FloatField(default=1.0, help_text='Margin of the document template in inches.', verbose_name='Page Margin'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='page_orientation',
            field=models.CharField(choices=[('portrait', 'Portrait'), ('landscape', 'Landscape')], default='portrait', help_text='Orientation of the document template.', max_length=10, verbose_name='Page Orientation'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='page_size',
            field=models.CharField(choices=[('A4', 'A4'), ('Letter', 'Letter'), ('A3', 'A3')], default='A4', help_text='Size of the document template.', max_length=10, verbose_name='Page Size'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='save_to_folder',
            field=models.ForeignKey(blank=True, help_text='Signifies to which folder a file generated from the template needs to be saved upon creation.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='bloomerp.filefolder', verbose_name='Save To Folder'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='style_sets',
            field=models.ManyToManyField(blank=True, help_text='Styling sets that can be applied to the document template.', related_name='document_templates', to='bloomerp.documenttemplatestyling', verbose_name='Style Sets'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='template',
            field=bloomerp.model_fields.text_editor_field.TextEditorField(blank=True, default='Hello world', help_text='Content of the template, including the variables.', verbose_name='Template'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='template_header',
            field=models.ForeignKey(blank=True, help_text='Header of the document template.', null=True, on_delete=django.db.models.deletion.SET_NULL, to='bloomerp.documenttemplateheader', verbose_name='Template Header'),
        ),
        migrations.AlterField(
            model_name='documenttemplate',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='header',
            field=models.ImageField(help_text='Image of the header.', upload_to='document_templates/headers', verbose_name='Header'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='height',
            field=models.FloatField(default=1.0, help_text='Height of the header in inches.', verbose_name='Height'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='margin_bottom',
            field=models.FloatField(default=0.0, help_text='Bottom margin of the header in inches.', verbose_name='Margin Bottom'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='margin_left',
            field=models.FloatField(default=1.0, help_text='Left margin of the header in inches.', verbose_name='Margin Left'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='margin_right',
            field=models.FloatField(default=1.0, help_text='Right margin of the header in inches.', verbose_name='Margin Right'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='margin_top',
            field=models.FloatField(default=0.5, help_text='Top margin of the header in inches.', verbose_name='Margin Top'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='name',
            field=models.CharField(help_text='Name of the template header.', max_length=100, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='documenttemplateheader',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='name',
            field=models.CharField(help_text='Name of the document template styling.', max_length=100, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='styling',
            field=bloomerp.model_fields.code_field.CodeField(default='', language='css', verbose_name='Styling'),
        ),
        migrations.AlterField(
            model_name='documenttemplatestyling',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='access_token',
            field=models.TextField(blank=True, help_text='Encrypted OAuth access token.', verbose_name='Access Token'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='email_address',
            field=models.EmailField(max_length=255, unique=True, verbose_name='Email Address'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='extra_settings',
            field=models.JSONField(blank=True, default=dict, help_text='Provider-specific settings that do not have dedicated fields yet.', verbose_name='Extra Settings'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='imap_host',
            field=models.CharField(blank=True, max_length=255, verbose_name='IMAP Host'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='imap_port',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='IMAP Port'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='imap_security',
            field=models.CharField(choices=[('ssl_tls', 'SSL/TLS'), ('starttls', 'STARTTLS'), ('none', 'None')], default='ssl_tls', max_length=32, verbose_name='IMAP Security'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='last_sync_error',
            field=models.TextField(blank=True, editable=False, verbose_name='Last Sync Error'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='last_sync_finished_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Last Sync Finished At'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='last_sync_started_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Last Sync Started At'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='last_validated_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Last Validated At'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='mailboxes',
            field=models.JSONField(blank=True, default=list, help_text='Cached list of folders/mailboxes for this account.', verbose_name='Mailboxes'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='name',
            field=models.CharField(blank=True, max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='next_sync_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Next Sync At'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='oauth_client_id',
            field=models.CharField(blank=True, max_length=255, verbose_name='OAuth Client ID'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='oauth_client_secret',
            field=models.TextField(blank=True, help_text='Encrypted OAuth client secret.', verbose_name='OAuth Client Secret'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='oauth_scopes',
            field=models.TextField(blank=True, help_text='Space-separated OAuth scopes requested for this account.', verbose_name='OAuth Scopes'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='oauth_tenant_id',
            field=models.CharField(blank=True, help_text='Provider tenant, directory, or workspace identifier when applicable.', max_length=255, verbose_name='OAuth Tenant ID'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='password',
            field=models.TextField(blank=True, help_text='Encrypted password or app password used for providers that support direct SMTP/IMAP authentication.', verbose_name='Password'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='provider',
            field=models.CharField(choices=[('imap', 'IMAP / SMTP')], default='imap', max_length=32, verbose_name='Provider'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='refresh_token',
            field=models.TextField(blank=True, help_text='Encrypted OAuth refresh token.', verbose_name='Refresh Token'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='smtp_host',
            field=models.CharField(blank=True, max_length=255, verbose_name='SMTP Host'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='smtp_port',
            field=models.PositiveIntegerField(blank=True, null=True, verbose_name='SMTP Port'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='smtp_security',
            field=models.CharField(choices=[('ssl_tls', 'SSL/TLS'), ('starttls', 'STARTTLS'), ('none', 'None')], default='starttls', max_length=32, verbose_name='SMTP Security'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='status',
            field=models.CharField(choices=[('draft', 'Draft'), ('active', 'Active'), ('error', 'Error')], default='draft', max_length=32, verbose_name='Status'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='sync_cursor',
            field=models.JSONField(blank=True, default=dict, help_text='Provider-specific cursor/state for incremental synchronization.', verbose_name='Sync Cursor'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='sync_enabled',
            field=models.BooleanField(default=True, help_text='Whether this account should be synchronized automatically.', verbose_name='Sync Enabled'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='sync_interval_minutes',
            field=models.PositiveIntegerField(default=5, help_text='Polling interval used by providers that synchronize on a schedule.', verbose_name='Sync Interval Minutes'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='sync_locked_until',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Sync Locked Until'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='sync_mode',
            field=models.CharField(blank=True, choices=[('polling', 'Polling'), ('push', 'Push')], help_text="Synchronization mode for this account. Defaults to the provider's preferred mode.", max_length=32, verbose_name='Sync Mode'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='token_expires_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='Token Expires At'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='username',
            field=models.CharField(blank=True, max_length=255, verbose_name='Username'),
        ),
        migrations.AlterField(
            model_name='emailaccount',
            name='validation_error',
            field=models.TextField(blank=True, editable=False, verbose_name='Validation Error'),
        ),
        migrations.AlterField(
            model_name='fieldpolicy',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='fieldpolicy',
            name='name',
            field=models.CharField(help_text='The name of the field-level access control policy.', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='fieldpolicy',
            name='rule',
            field=models.JSONField(help_text='A JSON representation of the field-level access control rules.', verbose_name='Rule'),
        ),
        migrations.AlterField(
            model_name='file',
            name='content_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='file',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='file',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='file',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='file',
            name='file',
            field=models.FileField(upload_to=bloomerp.files.legacy_migrations.legacy_file_upload_to, verbose_name='File'),
        ),
        migrations.AlterField(
            model_name='file',
            name='folder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='files', to='bloomerp.filefolder', verbose_name='Folder'),
        ),
        migrations.AlterField(
            model_name='file',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='file',
            name='meta',
            field=models.JSONField(blank=True, null=True, verbose_name='Meta'),
        ),
        migrations.AlterField(
            model_name='file',
            name='name',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='file',
            name='object_id',
            field=models.CharField(blank=True, max_length=36, null=True, verbose_name='Object ID'),
        ),
        migrations.AlterField(
            model_name='file',
            name='persisted',
            field=models.BooleanField(default=False, verbose_name='Persisted'),
        ),
        migrations.AlterField(
            model_name='file',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='content_type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='name',
            field=models.CharField(max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='object_id',
            field=models.CharField(blank=True, max_length=36, null=True, verbose_name='Object ID'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='bloomerp.filefolder', verbose_name='Parent'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='protected',
            field=models.BooleanField(default=False, help_text='Protected folders cannot be edited or deleted through the UI. This is useful for folders that are automatically created for objects, such as the module-level folders created for files.', verbose_name='Protected'),
        ),
        migrations.AlterField(
            model_name='filefolder',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='form',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='form',
            name='closes_at',
            field=models.DateTimeField(blank=True, help_text='The date and time after which the form will no longer accept submissions.', null=True, verbose_name='Closes At'),
        ),
        migrations.AlterField(
            model_name='form',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='form',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='form',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='form',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='form',
            name='description',
            field=models.TextField(blank=True, null=True, verbose_name='Description'),
        ),
        migrations.AlterField(
            model_name='form',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='form',
            name='initial_payload',
            field=models.JSONField(blank=True, default=dict, help_text='Initial payload for the form', verbose_name='Initial Payload'),
        ),
        migrations.AlterField(
            model_name='form',
            name='layout',
            field=models.JSONField(blank=True, default=dict, verbose_name='Layout'),
        ),
        migrations.AlterField(
            model_name='form',
            name='max_submissions',
            field=models.IntegerField(blank=True, help_text='Maximum number of submissions possible for the form', null=True, verbose_name='Max Submissions'),
        ),
        migrations.AlterField(
            model_name='form',
            name='max_submissions_per_ip',
            field=models.IntegerField(blank=True, help_text='Maximum number of submissions per IP address', null=True, verbose_name='Max Submissions Per IP'),
        ),
        migrations.AlterField(
            model_name='form',
            name='name',
            field=models.CharField(default='Untitled form', help_text='The name of the form', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='form',
            name='opens_at',
            field=models.DateTimeField(blank=True, help_text='The date and time from which the form will accept submissions.', null=True, verbose_name='Opens At'),
        ),
        migrations.AlterField(
            model_name='form',
            name='public_embed_enabled',
            field=models.BooleanField(default=False, help_text='Whether the form can be embedded in a public page.', verbose_name='Public Embed Enabled'),
        ),
        migrations.AlterField(
            model_name='form',
            name='requires_authentication',
            field=models.BooleanField(default=False, help_text='Whether the form requires an authenticated user in order to be accessible.', verbose_name='Requires Authentication'),
        ),
        migrations.AlterField(
            model_name='form',
            name='requires_review',
            field=models.BooleanField(default=True, help_text='Whether the form submission needs to be reviewed before it is persisted.', verbose_name='Requires Review'),
        ),
        migrations.AlterField(
            model_name='form',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='data',
            field=models.JSONField(verbose_name='Data'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='form',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='submissions', to='bloomerp.form', verbose_name='Form'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='ip_address',
            field=models.GenericIPAddressField(blank=True, null=True, verbose_name='IP Address'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='persisted',
            field=models.BooleanField(default=False, editable=False, help_text='Whether the form was persisted', verbose_name='Persisted'),
        ),
        migrations.AlterField(
            model_name='formsubmission',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='initial_default',
            field=models.BooleanField(default=False, help_text="Indicates if this preference is the initial default for the user. This is used to determine the user's default preference when they first create an account.", verbose_name='Initial Default'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='name',
            field=models.CharField(default='Default', help_text='Optional name for this preference, for user reference', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='selected',
            field=models.BooleanField(default=False, help_text='Indicates if this preference is currently selected for the user. Only one preference per user can be selected at a time.', verbose_name='Selected'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='shared_with_groups',
            field=models.ManyToManyField(blank=True, help_text='Groups with whom this preference is shared.', related_name='shared_%(class)s_preferences', to='auth.group', verbose_name='Shared With Groups'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='shared_with_users',
            field=models.ManyToManyField(blank=True, help_text='Users with whom this preference is shared.', related_name='shared_%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='Shared With Users'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='source_object',
            field=models.ForeignKey(blank=True, help_text='Reference to the original preference from which this preference was derived. This is used to track the origin of derived preferences.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='derived_%(class)s_preferences', to='bloomerp.inbox', verbose_name='Source Object'),
        ),
        migrations.AlterField(
            model_name='inbox',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='inbox',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='folders', to='bloomerp.inbox', verbose_name='Inbox'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='related_object_id',
            field=models.CharField(blank=True, max_length=255, null=True, verbose_name='Related Object ID'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='type',
            field=models.CharField(choices=[('all', 'All'), ('in_app_notifications', 'Notifications'), ('email', 'Emails')], max_length=50, verbose_name='Type'),
        ),
        migrations.AlterField(
            model_name='inboxfolder',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='actor',
            field=models.CharField(blank=True, help_text='The actor or entity associated with the inbox item.', max_length=255, null=True, verbose_name='Actor'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='datetime_received',
            field=models.DateTimeField(blank=True, db_index=True, editable=False, help_text='Timestamp when the inbox item was received by its source system.', null=True, verbose_name='Datetime Received'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='folder',
            field=models.ForeignKey(help_text='The folder to which this inbox item belongs.', on_delete=django.db.models.deletion.CASCADE, related_name='inbox_items', to='bloomerp.inboxfolder', verbose_name='Folder'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='is_read',
            field=models.BooleanField(default=False, help_text='Indicates whether the inbox item has been read by the user.', verbose_name='Is Read'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='item_type',
            field=models.CharField(choices=[('notification', 'Notification'), ('email', 'Email')], max_length=50, verbose_name='Item Type'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='raw_meta_data',
            field=models.JSONField(blank=True, help_text='Optional JSON field to store additional metadata related to the inbox item.', null=True, verbose_name='Raw Meta Data'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='related_item_id',
            field=models.CharField(blank=True, help_text="Optional reference to the source item's ID, if applicable.", max_length=1000, null=True, verbose_name='Related Item ID'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='snippet',
            field=models.TextField(blank=True, help_text='A brief snippet or summary of the inbox item content.', null=True, verbose_name='Snippet'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='title',
            field=models.CharField(help_text='The title of the inbox item.', max_length=1000, verbose_name='Title'),
        ),
        migrations.AlterField(
            model_name='inboxitem',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='completed_at',
            field=models.DateTimeField(blank=True, editable=False, null=True, verbose_name='Completed At'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='description',
            field=models.TextField(blank=True, help_text='A detailed description of the initiative', null=True, verbose_name='Description'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='labels',
            field=models.ManyToManyField(blank=True, help_text='Labels assigned to the initiative', related_name='initiatives', to='bloomerp.todolabel', verbose_name='Labels'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='name',
            field=models.CharField(help_text='The name of the initiative', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='owner',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='owned_initiatives', to=settings.AUTH_USER_MODEL, verbose_name='Owner'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='start_date',
            field=models.DateField(blank=True, null=True, verbose_name='Start Date'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='status',
            field=models.CharField(choices=[('backlog', 'Backlog'), ('in_progress', 'In Progress'), ('on_hold', 'On Hold'), ('completed', 'Completed'), ('canceled', 'Canceled')], default='backlog', max_length=20, verbose_name='Status'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='target_date',
            field=models.DateField(blank=True, null=True, verbose_name='Target Date'),
        ),
        migrations.AlterField(
            model_name='initiative',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='description',
            field=models.TextField(blank=True, help_text='A description of the access control policy.', verbose_name='Description'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='field_policy',
            field=models.ForeignKey(help_text='The field-level policy associated with this access control policy.', on_delete=django.db.models.deletion.CASCADE, related_name='policies', to='bloomerp.fieldpolicy', verbose_name='Field Policy'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='global_permissions',
            field=models.ManyToManyField(blank=True, help_text='Global permissions applied by this policy.', related_name='access_control_policies', to='auth.permission', verbose_name='Global Permissions'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='groups',
            field=models.ManyToManyField(blank=True, help_text='Groups assigned to this access control policy.', related_name='access_control_policies', to='auth.group', verbose_name='Groups'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='name',
            field=models.CharField(help_text='The name of the access control policy.', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='row_policy',
            field=models.ForeignKey(help_text='The row-level policy associated with this access control policy.', on_delete=django.db.models.deletion.CASCADE, related_name='policies', to='bloomerp.rowpolicy', verbose_name='Row Policy'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='policy',
            name='users',
            field=models.ManyToManyField(blank=True, help_text='Users assigned to this access control policy.', related_name='access_control_policies', to=settings.AUTH_USER_MODEL, verbose_name='Users'),
        ),
        migrations.AlterField(
            model_name='rowpolicy',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='rowpolicy',
            name='name',
            field=models.CharField(blank=True, default='', help_text='The name of the row-level access control policy.', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='rowpolicyrule',
            name='permissions',
            field=models.ManyToManyField(related_name='row_policy_rules', through='bloomerp.RowPolicyRulePermission', to='auth.permission', verbose_name='Permissions'),
        ),
        migrations.AlterField(
            model_name='rowpolicyrule',
            name='row_policy',
            field=models.ForeignKey(help_text='The row-level access control policy this rule belongs to.', on_delete=django.db.models.deletion.CASCADE, related_name='rules', to='bloomerp.rowpolicy', verbose_name='Row Policy'),
        ),
        migrations.AlterField(
            model_name='rowpolicyrule',
            name='rule',
            field=models.JSONField(help_text='A JSON representation of the row-level access control rule.', verbose_name='Rule'),
        ),
        migrations.AlterField(
            model_name='rowpolicyrulepermission',
            name='permission',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='auth.permission', verbose_name='Permission'),
        ),
        migrations.AlterField(
            model_name='rowpolicyrulepermission',
            name='row_policy_rule',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='bloomerp.rowpolicyrule', verbose_name='Row Policy Rule'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='initial_default',
            field=models.BooleanField(default=False, help_text="Indicates if this preference is the initial default for the user. This is used to determine the user's default preference when they first create an account.", verbose_name='Initial Default'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='name',
            field=models.CharField(default='Default', help_text='Optional name for this preference, for user reference', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='selected',
            field=models.BooleanField(default=False, help_text='Indicates if this preference is currently selected for the user. Only one preference per user can be selected at a time.', verbose_name='Selected'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='shared_with_groups',
            field=models.ManyToManyField(blank=True, help_text='Groups with whom this preference is shared.', related_name='shared_%(class)s_preferences', to='auth.group', verbose_name='Shared With Groups'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='shared_with_users',
            field=models.ManyToManyField(blank=True, help_text='Users with whom this preference is shared.', related_name='shared_%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='Shared With Users'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='source_object',
            field=models.ForeignKey(blank=True, help_text='Reference to the original preference from which this preference was derived. This is used to track the origin of derived preferences.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='derived_%(class)s_preferences', to='bloomerp.sidebar', verbose_name='Source Object'),
        ),
        migrations.AlterField(
            model_name='sidebar',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='color',
            field=models.CharField(default='#bfdbfe', help_text='Hex color code for the sidebar item (e.g. #FF5733).', max_length=7, verbose_name='Color'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='icon',
            field=bloomerp.model_fields.icon_field.IconField(help_text='Icon for the particular sidebar item.', max_length=100, verbose_name='Icon'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='is_folder',
            field=models.BooleanField(default=False, verbose_name='Is Folder'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='name',
            field=models.CharField(help_text='Name of the sidebar item.', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='bloomerp.sidebaritem', verbose_name='Parent'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='position',
            field=models.PositiveIntegerField(default=0, help_text='Position of the sidebar item among its siblings. Lower numbers appear first.', verbose_name='Position'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='sidebar',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='bloomerp.sidebar', verbose_name='Sidebar'),
        ),
        migrations.AlterField(
            model_name='sidebaritem',
            name='url',
            field=models.CharField(blank=True, help_text='URL that the sidebar item points to.', max_length=2048, null=True, verbose_name='URL'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='name',
            field=models.CharField(max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='query',
            field=bloomerp.model_fields.code_field.CodeField(help_text='SQL Query to execute', language='sql', verbose_name='Query'),
        ),
        migrations.AlterField(
            model_name='sqlquery',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='auto_generated',
            field=models.BooleanField(default=False, verbose_name='Auto Generated'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='description',
            field=models.TextField(blank=True, help_text='Description of the widget', null=True, verbose_name='Description'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='icon',
            field=bloomerp.model_fields.icon_field.IconField(default='fa fa-chart-simple', max_length=100, verbose_name='Icon'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='name',
            field=models.CharField(help_text='Name of the widget', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='schema',
            field=models.JSONField(verbose_name='Schema'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='type',
            field=models.CharField(choices=bloomerp.models.workspaces.tile.get_tile_type_choices, help_text='The type of tile', max_length=32, verbose_name='Type'),
        ),
        migrations.AlterField(
            model_name='tile',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='assigned_to',
            field=models.ForeignKey(blank=True, help_text='The user to whom the todo is assigned', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='todos', to=settings.AUTH_USER_MODEL, verbose_name='Assigned To'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='content',
            field=bloomerp.model_fields.text_editor_field.TextEditorField(blank=True, null=True, verbose_name='Content'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='content_type',
            field=models.ForeignKey(blank=True, help_text='The content type of the related object', null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='datetime_completed',
            field=models.DateTimeField(blank=True, editable=False, help_text='The date and time when the todo was completed', null=True, verbose_name='Date Completed'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='effort',
            field=models.IntegerField(blank=True, choices=[(1, 'XS'), (2, 'S'), (4, 'M'), (8, 'L'), (16, 'XL')], default=4, help_text='The effort required for the todo', null=True, verbose_name='Effort'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='initiative',
            field=models.ForeignKey(blank=True, help_text='The initiative this todo belongs to', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='todos', to='bloomerp.initiative', verbose_name='Initiative'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='labels',
            field=models.ManyToManyField(blank=True, help_text='Labels assigned to the todo', to='bloomerp.todolabel', verbose_name='Labels'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='object_id',
            field=models.CharField(blank=True, help_text='The ID of the related object', max_length=36, null=True, verbose_name='Object ID'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='priority',
            field=models.CharField(choices=[('urgent', 'Urgent'), ('high', 'High'), ('medium', 'Medium'), ('low', 'Low')], default='medium', help_text='The priority of the todo', max_length=20, verbose_name='Priority'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='requested_by',
            field=models.ForeignKey(blank=True, help_text='The user who requested the todo', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='requested_todos', to=settings.AUTH_USER_MODEL, verbose_name='Requested By'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='required_by',
            field=models.DateField(blank=True, help_text='The date by which the todo is required', null=True, verbose_name='Required By'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='status',
            field=models.CharField(choices=[('backlog', 'Backlog'), ('in_progress', 'In Progress'), ('in_review', 'In Review'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('duplicate', 'Duplicate')], default='backlog', max_length=50, verbose_name='Status'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='title',
            field=models.CharField(help_text='The name of the todo', max_length=255, verbose_name='Title'),
        ),
        migrations.AlterField(
            model_name='todo',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='color',
            field=models.CharField(max_length=7, verbose_name='Color'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='name',
            field=models.CharField(max_length=100, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='todolabel',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='user',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='user',
            name='date_view_preference',
            field=models.CharField(choices=[('d-m-Y', 'Day-Month-Year (15-08-2000)'), ('m-d-Y', 'Month-Day-Year (08-15-2000)'), ('Y-m-d', 'Year-Month-Day (2000-08-15)')], default='d-m-Y', help_text='The date format to be used in the application', max_length=20, verbose_name='Date View Preference'),
        ),
        migrations.AlterField(
            model_name='user',
            name='datetime_view_preference',
            field=models.CharField(choices=[('d-m-Y H:i', 'Day-Month-Year Hour:Minute (15-08-2000 12:30)'), ('m-d-Y H:i', 'Month-Day-Year Hour:Minute (08-15-2000 12:30)'), ('Y-m-d H:i', 'Year-Month-Day Hour:Minute (2000-08-15 12:30)')], default='d-m-Y H:i', help_text='The datetime format to be used in the application', max_length=20, verbose_name='Datetime View Preference'),
        ),
        migrations.AlterField(
            model_name='user',
            name='detail_sidebar_view_preference',
            field=models.CharField(choices=[('activity', 'Activity'), ('comments', 'Comments')], default='activity', help_text='The detail view sidebar panel to show first', max_length=20, verbose_name='Detail Sidebar View Preference'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabitem',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabitem',
            name='name',
            field=models.CharField(max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabitem',
            name='parent',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='bloomerp.userdetailviewtabitem', verbose_name='Parent'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabitem',
            name='position',
            field=models.PositiveIntegerField(default=0, verbose_name='Position'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabitem',
            name='preference',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='bloomerp.userdetailviewtabspreference', verbose_name='Preference'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabitem',
            name='url',
            field=models.CharField(blank=True, max_length=2048, null=True, verbose_name='URL'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='initial_default',
            field=models.BooleanField(default=False, help_text="Indicates if this preference is the initial default for the user. This is used to determine the user's default preference when they first create an account.", verbose_name='Initial Default'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='name',
            field=models.CharField(default='Default', help_text='Optional name for this preference, for user reference', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='selected',
            field=models.BooleanField(default=False, help_text='Indicates if this preference is currently selected for the user. Only one preference per user can be selected at a time.', verbose_name='Selected'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='shared_with_groups',
            field=models.ManyToManyField(blank=True, help_text='Groups with whom this preference is shared.', related_name='shared_%(class)s_preferences', to='auth.group', verbose_name='Shared With Groups'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='shared_with_users',
            field=models.ManyToManyField(blank=True, help_text='Users with whom this preference is shared.', related_name='shared_%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='Shared With Users'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='source_object',
            field=models.ForeignKey(blank=True, help_text='Reference to the original preference from which this preference was derived. This is used to track the origin of derived preferences.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='derived_%(class)s_preferences', to='bloomerp.userdetailviewtabspreference', verbose_name='Source Object'),
        ),
        migrations.AlterField(
            model_name='userdetailviewtabspreference',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='avatar',
            field=models.ImageField(blank=True, null=True, upload_to='avatars/', verbose_name='Avatar'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='id',
            field=models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, verbose_name='ID'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='selected_inbox_folder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='users_with_selected_inbox_folder_preference', to='bloomerp.inboxfolder', verbose_name='Selected Inbox Folder'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='userinboxpreference',
            name='user',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='inbox_preference', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='default_filters',
            field=models.JSONField(default=dict, verbose_name='Default Filters'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='display_fields',
            field=models.JSONField(default=bloomerp.models.users.user_list_view_preference.get_default_display_fields, verbose_name='Display Fields'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='initial_default',
            field=models.BooleanField(default=False, help_text="Indicates if this preference is the initial default for the user. This is used to determine the user's default preference when they first create an account.", verbose_name='Initial Default'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='name',
            field=models.CharField(default='Default', help_text='Optional name for this preference, for user reference', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='options',
            field=models.JSONField(default=dict, verbose_name='Options'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='selected',
            field=models.BooleanField(default=False, help_text='Indicates if this preference is currently selected for the user. Only one preference per user can be selected at a time.', verbose_name='Selected'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='shared_with_groups',
            field=models.ManyToManyField(blank=True, help_text='Groups with whom this preference is shared.', related_name='shared_%(class)s_preferences', to='auth.group', verbose_name='Shared With Groups'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='shared_with_users',
            field=models.ManyToManyField(blank=True, help_text='Users with whom this preference is shared.', related_name='shared_%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='Shared With Users'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='source_object',
            field=models.ForeignKey(blank=True, help_text='Reference to the original preference from which this preference was derived. This is used to track the origin of derived preferences.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='derived_%(class)s_preferences', to='bloomerp.userlistviewpreference', verbose_name='Source Object'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='split_view_enabled',
            field=models.BooleanField(default=False, verbose_name='Split View Enabled'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='userlistviewpreference',
            name='view_type',
            field=models.CharField(choices=[('table', 'Table'), ('kanban', 'Kanban'), ('card', 'Card'), ('calendar', 'Calendar'), ('gant', 'Gantt'), ('pivot_table', 'Pivot')], default='table', max_length=50, verbose_name='View Type'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype', verbose_name='Content Type'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='initial_default',
            field=models.BooleanField(default=False, help_text="Indicates if this preference is the initial default for the user. This is used to determine the user's default preference when they first create an account.", verbose_name='Initial Default'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='layout',
            field=models.JSONField(blank=True, default=dict, verbose_name='Layout'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='name',
            field=models.CharField(default='Default', help_text='Optional name for this preference, for user reference', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='selected',
            field=models.BooleanField(default=False, help_text='Indicates if this preference is currently selected for the user. Only one preference per user can be selected at a time.', verbose_name='Selected'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='shared_with_groups',
            field=models.ManyToManyField(blank=True, help_text='Groups with whom this preference is shared.', related_name='shared_%(class)s_preferences', to='auth.group', verbose_name='Shared With Groups'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='shared_with_users',
            field=models.ManyToManyField(blank=True, help_text='Users with whom this preference is shared.', related_name='shared_%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='Shared With Users'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='source_object',
            field=models.ForeignKey(blank=True, help_text='Reference to the original preference from which this preference was derived. This is used to track the origin of derived preferences.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='derived_%(class)s_preferences', to='bloomerp.userobjectlayoutpreference', verbose_name='Source Object'),
        ),
        migrations.AlterField(
            model_name='userobjectlayoutpreference',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='active',
            field=models.BooleanField(default=True, help_text='Whether the workflow is active or not', verbose_name='Active'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='enable_logging',
            field=models.BooleanField(default=False, help_text='Whether to enable logging for this workflow. Disabling logging may improve performance but will result in no detailed execution history being stored.', verbose_name='Enable Logging'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='name',
            field=models.CharField(help_text='The name of the workflow.', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='run_asynchronously',
            field=models.BooleanField(default=False, help_text='Whether runs asynchronously', verbose_name='Run Asynchronously'),
        ),
        migrations.AlterField(
            model_name='workflow',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='workflowedge',
            name='from_node',
            field=models.ForeignKey(help_text='The node where this edge starts.', on_delete=django.db.models.deletion.CASCADE, related_name='outgoing_edges', to='bloomerp.workflownode', verbose_name='From Node'),
        ),
        migrations.AlterField(
            model_name='workflowedge',
            name='name',
            field=models.CharField(blank=True, help_text='A descriptive name for the edge.', max_length=1000, null=True, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='workflowedge',
            name='to_node',
            field=models.ForeignKey(help_text='The node where this edge ends.', on_delete=django.db.models.deletion.CASCADE, related_name='incoming_edges', to='bloomerp.workflownode', verbose_name='To Node'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='config',
            field=models.JSONField(default=dict, help_text='The configuration for the workflow node.', verbose_name='Config'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='created_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_created', to=settings.AUTH_USER_MODEL, verbose_name='Created By'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='name',
            field=models.CharField(blank=True, help_text='The name of the workflow node.', max_length=255, null=True, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='pos_x',
            field=models.IntegerField(default=0, help_text='The X position of the node in the workflow editor.', verbose_name='Pos X'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='pos_y',
            field=models.IntegerField(default=0, help_text='The Y position of the node in the workflow editor.', verbose_name='Pos Y'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='type',
            field=models.CharField(choices=[('TRIGGER', 'Trigger'), ('ACTION', 'Action'), ('FLOW', 'Flow')], help_text='The type of the workflow node.', max_length=32, verbose_name='Type'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='updated_by',
            field=bloomerp.model_fields.user_field.UserField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='%(class)s_updated', to=settings.AUTH_USER_MODEL, verbose_name='Updated By'),
        ),
        migrations.AlterField(
            model_name='workflownode',
            name='workflow',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='nodes', to='bloomerp.workflow', verbose_name='Workflow'),
        ),
        migrations.AlterField(
            model_name='workflowrun',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='workflowrun',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='workflowrun',
            name='workflow',
            field=models.ForeignKey(editable=False, help_text='The workflow associated with this run.', on_delete=django.db.models.deletion.CASCADE, related_name='runs', to='bloomerp.workflow', verbose_name='Workflow'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='action_id',
            field=models.CharField(help_text='The identifier of the action being executed in this step.', max_length=255, verbose_name='Action ID'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='datetime_created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Datetime Created'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='datetime_updated',
            field=models.DateTimeField(auto_now=True, verbose_name='Datetime Updated'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='node',
            field=models.ForeignKey(blank=True, help_text='Reference to node object', null=True, on_delete=django.db.models.deletion.SET_NULL, to='bloomerp.workflownode', verbose_name='Node'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='output_file',
            field=models.FileField(blank=True, help_text='Serialized output produced by this workflow node execution.', null=True, upload_to='workflow_run_outputs/', verbose_name='Output File'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='sequence',
            field=models.PositiveIntegerField(help_text='The sequence number of this step within the workflow run.', verbose_name='Sequence'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='state',
            field=models.JSONField(blank=True, help_text='Serializable workflow execution state captured after this step.', null=True, verbose_name='State'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='status',
            field=models.CharField(choices=[('PAUSED', 'Paused'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed'), ('CANCELLED', 'Cancelled')], default='COMPLETED', help_text='The status of this workflow run step.', max_length=20, verbose_name='Status'),
        ),
        migrations.AlterField(
            model_name='workflowrunstep',
            name='workflow_run',
            field=models.ForeignKey(help_text='The workflow run that this step belongs to.', on_delete=django.db.models.deletion.CASCADE, related_name='steps', to='bloomerp.workflowrun', verbose_name='Workflow Run'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='initial_default',
            field=models.BooleanField(default=False, help_text="Indicates if this preference is the initial default for the user. This is used to determine the user's default preference when they first create an account.", verbose_name='Initial Default'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='layout',
            field=models.JSONField(blank=True, default=dict, verbose_name='Layout'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='module_id',
            field=models.CharField(blank=True, default=None, max_length=255, null=True, verbose_name='Module ID'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='name',
            field=models.CharField(default='Default', help_text='Optional name for this preference, for user reference', max_length=255, verbose_name='Name'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='selected',
            field=models.BooleanField(default=False, help_text='Indicates if this preference is currently selected for the user. Only one preference per user can be selected at a time.', verbose_name='Selected'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='shared_with_groups',
            field=models.ManyToManyField(blank=True, help_text='Groups with whom this preference is shared.', related_name='shared_%(class)s_preferences', to='auth.group', verbose_name='Shared With Groups'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='shared_with_users',
            field=models.ManyToManyField(blank=True, help_text='Users with whom this preference is shared.', related_name='shared_%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='Shared With Users'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='source_object',
            field=models.ForeignKey(blank=True, help_text='Reference to the original preference from which this preference was derived. This is used to track the origin of derived preferences.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='derived_%(class)s_preferences', to='bloomerp.workspace', verbose_name='Source Object'),
        ),
        migrations.AlterField(
            model_name='workspace',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)s_preferences', to=settings.AUTH_USER_MODEL, verbose_name='User'),
        ),
    ]

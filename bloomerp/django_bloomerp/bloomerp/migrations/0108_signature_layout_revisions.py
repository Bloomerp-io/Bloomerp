"""Associate retained signing revisions with their originating document template."""

from collections import defaultdict
from typing import ClassVar
from uuid import UUID

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation


def link_layout_templates(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Backfill explicit defaults or single-template previews without guessing ambiguous history."""
    database = schema_editor.connection.alias
    template_model = apps.get_model("bloomerp", "DocumentTemplate")
    layout_model = apps.get_model("bloomerp", "SignatureLayout")
    reference_model = apps.get_model("bloomerp", "FileReference")
    type_model = apps.get_model("contenttypes", "ContentType")
    templates = dict(
        template_model.objects.using(database).values_list(
            "pk", "default_signature_layout_id"
        )
    )
    defaults: dict[UUID, set[UUID]] = defaultdict(set)
    for template_id, layout_id in templates.items():
        if layout_id:
            defaults[layout_id].add(template_id)
    template_type = (
        type_model.objects.using(database)
        .filter(app_label="bloomerp", model="documenttemplate")
        .first()
    )
    previews: dict[UUID, set[UUID]] = defaultdict(set)
    if template_type:
        for file_id, identifier in (
            reference_model.objects.using(database)
            .filter(
                content_type_id=template_type.pk,
                application_field_id__isnull=True,
                occurrence_id__isnull=True,
            )
            .values_list("file_id", "object_id")
            .iterator()
        ):
            try:
                template_id = UUID(str(identifier))
            except (ValueError, TypeError):
                continue
            if template_id in templates:
                previews[file_id].add(template_id)
    candidates: dict[tuple[UUID, int], list[UUID]] = defaultdict(list)
    for layout in layout_model.objects.using(database).all().iterator():
        owners = defaults.get(layout.pk) or previews.get(layout.preview_file_id, set())
        if len(owners) == 1:
            candidates[(next(iter(owners)), layout.revision)].append(layout.pk)
    for (template_id, _revision), identities in candidates.items():
        if len(identities) > 1:
            identities = [
                identity
                for identity in identities
                if template_id in defaults.get(identity, set())
            ]
        if len(identities) == 1:
            layout_model.objects.using(database).filter(pk=identities[0]).update(
                document_template_id=template_id
            )


class Migration(migrations.Migration):
    """Keep revision ownership explicit while preserving legacy and ambiguous layouts."""

    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0107_signature_email_delivery"),
    ]
    operations: ClassVar[list[Operation]] = [
        migrations.AddField(
            model_name="signaturelayout",
            name="document_template",
            field=models.ForeignKey(
                to="bloomerp.documenttemplate",
                related_name="signature_layout_revisions",
                on_delete=django.db.models.deletion.PROTECT,
                null=True,
                blank=True,
                verbose_name="Document template",
            ),
        ),
        migrations.RunPython(link_layout_templates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="signaturelayout",
            constraint=models.UniqueConstraint(
                fields=("document_template", "revision"),
                name="signature_layout_template_revision_unique",
            ),
        ),
    ]

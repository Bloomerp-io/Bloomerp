from django.db import migrations, models


def migrate_condition_edges_to_true_port(apps, schema_editor):
    WorkflowEdge = apps.get_model("bloomerp", "WorkflowEdge")
    WorkflowEdge.objects.filter(
        from_node__sub_type__in=["IF_CONDITION", "OBJECT_IF_CONDITION"],
        output_port="default",
    ).update(output_port="true")


class Migration(migrations.Migration):
    dependencies = [
        ("bloomerp", "0066_rename_gant_dataview_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowedge",
            name="output_port",
            field=models.CharField(
                default="default",
                help_text="The output port on the source node used by this edge.",
                max_length=100,
                verbose_name="Output Port",
            ),
        ),
        migrations.RunPython(
            migrate_condition_edges_to_true_port,
            migrations.RunPython.noop,
        ),
    ]

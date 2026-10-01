"""Allow registered artifact types while retaining legacy payload validation on the model."""

from typing import ClassVar

from django.db import migrations, models

from bloomerp.models.agents.fields import AgentJSONField


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("bloomerp", "0079_agent_execution_state")
    ]

    operations: ClassVar[list[migrations.operations.base.Operation]] = [
        migrations.AlterField(
            model_name="aiartifact", name="kind", field=models.CharField(max_length=100)
        ),
        migrations.AlterField(
            model_name="aiartifact",
            name="schema_version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="aiartifact",
            name="payload",
            field=AgentJSONField(schema="object.v1"),
        ),
    ]

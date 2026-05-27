from django.db import migrations


def group_existing_row_policy_rules(apps, schema_editor):
    RowPolicyRule = apps.get_model("bloomerp", "RowPolicyRule")

    for row_policy_rule in RowPolicyRule.objects.using(schema_editor.connection.alias).all():
        rule = row_policy_rule.rule
        if not isinstance(rule, dict) or "conditions" in rule:
            continue

        row_policy_rule.rule = {
            "connector": "OR",
            "conditions": [rule],
        }
        row_policy_rule.save(update_fields=["rule"])


class Migration(migrations.Migration):

    dependencies = [
        ("bloomerp", "0012_activitylog_action"),
    ]

    operations = [
        migrations.RunPython(group_existing_row_policy_rules),
    ]

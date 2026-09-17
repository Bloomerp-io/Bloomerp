from copy import deepcopy

from django.db import migrations


SCALAR_OPTION_KEYS = {
    "kanban": {"group_by_field_id": "group_by_field"},
    "calendar": {
        "start_field_id": "start_field",
        "end_field_id": "end_field",
        "color_grouping_field_id": "color_grouping_field",
    },
    "gantt": {
        "start_field_id": "start_field",
        "end_field_id": "end_field",
        "dependency_from_field_id": "dependency_from_field",
        "dependency_for_field_id": "dependency_for_field",
    },
}

LIST_OPTION_KEYS = {
    "pivot_table": {
        "row_field_ids": "row_fields",
        "column_field_ids": "column_fields",
        "value_field_ids": "value_fields",
    },
}


def _field_names_by_id(ApplicationField, content_type_id):
    return dict(
        ApplicationField.objects.filter(content_type_id=content_type_id).values_list(
            "id", "field"
        )
    )


def _field_ids_by_name(ApplicationField, content_type_id):
    return dict(
        ApplicationField.objects.filter(content_type_id=content_type_id).values_list(
            "field", "id"
        )
    )


def migrate_options_to_field_names(apps, _schema_editor):
    UserListViewPreference = apps.get_model("bloomerp", "UserListViewPreference")
    ApplicationField = apps.get_model("bloomerp", "ApplicationField")

    for preference in UserListViewPreference.objects.iterator():
        options = deepcopy(preference.options or {})
        names_by_id = _field_names_by_id(ApplicationField, preference.content_type_id)
        changed = False

        for view_type, key_mapping in SCALAR_OPTION_KEYS.items():
            view_options = options.get(view_type)
            if not isinstance(view_options, dict):
                continue
            for old_key, new_key in key_mapping.items():
                if old_key not in view_options:
                    continue
                field_id = view_options.pop(old_key)
                view_options[new_key] = names_by_id.get(field_id)
                changed = True

        for view_type, key_mapping in LIST_OPTION_KEYS.items():
            view_options = options.get(view_type)
            if not isinstance(view_options, dict):
                continue
            for old_key, new_key in key_mapping.items():
                if old_key not in view_options:
                    continue
                field_ids = view_options.pop(old_key) or []
                view_options[new_key] = [
                    names_by_id[field_id]
                    for field_id in field_ids
                    if field_id in names_by_id
                ]
                changed = True

            if "value_field_id" in view_options:
                field_id = view_options.pop("value_field_id")
                view_options["value_fields"] = (
                    [names_by_id[field_id]] if field_id in names_by_id else []
                )
                changed = True

        if changed:
            preference.options = options
            preference.save(update_fields=["options"])


def migrate_options_to_field_ids(apps, _schema_editor):
    UserListViewPreference = apps.get_model("bloomerp", "UserListViewPreference")
    ApplicationField = apps.get_model("bloomerp", "ApplicationField")

    scalar_reverse = {
        view_type: {new_key: old_key for old_key, new_key in key_mapping.items()}
        for view_type, key_mapping in SCALAR_OPTION_KEYS.items()
    }
    list_reverse = {
        view_type: {new_key: old_key for old_key, new_key in key_mapping.items()}
        for view_type, key_mapping in LIST_OPTION_KEYS.items()
    }

    for preference in UserListViewPreference.objects.iterator():
        options = deepcopy(preference.options or {})
        ids_by_name = _field_ids_by_name(ApplicationField, preference.content_type_id)
        changed = False

        for view_type, key_mapping in scalar_reverse.items():
            view_options = options.get(view_type)
            if not isinstance(view_options, dict):
                continue
            for old_key, new_key in key_mapping.items():
                if old_key not in view_options:
                    continue
                field_name = view_options.pop(old_key)
                view_options[new_key] = ids_by_name.get(field_name)
                changed = True

        for view_type, key_mapping in list_reverse.items():
            view_options = options.get(view_type)
            if not isinstance(view_options, dict):
                continue
            for old_key, new_key in key_mapping.items():
                if old_key not in view_options:
                    continue
                field_names = view_options.pop(old_key) or []
                view_options[new_key] = [
                    ids_by_name[field_name]
                    for field_name in field_names
                    if field_name in ids_by_name
                ]
                changed = True

        if changed:
            preference.options = options
            preference.save(update_fields=["options"])


class Migration(migrations.Migration):
    dependencies = [("bloomerp", "0070_saved_default_filters")]

    operations = [
        migrations.RunPython(
            migrate_options_to_field_names,
            migrate_options_to_field_ids,
        )
    ]

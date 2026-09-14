from django.forms.models import ModelMultipleChoiceField

from bloomerp.field_types.utils.form_field_factories import form
from bloomerp.field_types.utils.render_value_functions import (
    render_foreign_key_dataview_value,
)
from bloomerp.field_types.display_options import LABEL_OPTION, FieldDisplayOption
from bloomerp.field_types.lookups import ONE_TO_MANY_LOOKUPS
from bloomerp.lookups import builtins as lookups
from bloomerp.field_types.construction import (
    BLANK_FIELD_OPTION,
    COMMON_RELATION_FIELD_OPTIONS,
    DB_INDEX_FIELD_OPTION,
    HELP_TEXT_FIELD_OPTION,
    NULL_FIELD_OPTION,
    ON_DELETE_FIELD_OPTION,
    RELATED_NAME_FIELD_OPTION,
    TO_FIELD_OPTION,
    UNIQUE_FIELD_OPTION,
    VERBOSE_NAME_FIELD_OPTION,
)
from bloomerp.field_types.utils.render_value_functions import render_m2m_dataview_value
from bloomerp.field_types.utils.widget_factories import inline_widget, widget
from bloomerp.form_fields.files_relation_field import FilesRelationField
from bloomerp.form_fields.one_to_many_field import OneToManyField
from bloomerp.form_fields.ordered_multiple_choice_field import (
    OrderedMultipleChoiceField,
)
from bloomerp.lookups.definition import BoundLookup
from bloomerp.model_fields.one_to_one_user_field import OneToOneUserField
from bloomerp.model_fields.user_field import UserField
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.object_files_widget import ObjectFilesWidget
from django import forms
from django.db import models
from bloomerp.field_types.registry import (
    FieldConstruction,
    FieldTypeDefinition,
    FieldTypeRegistry,
)
from bloomerp.field_types.builtins.display import (
    BEHAVIORS_DISPLAY_OPTION,
    get_related_model_field_choices,
)
from bloomerp.field_types.utils.widget_factories import relation_widget

REL_VALUES_IN_LOOKUP = BoundLookup(
    lookups.VALUES_IN,
    form_factory=lambda context: ModelMultipleChoiceField(
        queryset=context.application_field.related_model.model_class().objects.all(),
        widget=ForeignFieldWidget(
            model = context.application_field.related_model.model_class(),
            attrs={
                "is_m2m" : True
            }
        )
    )    
)


FOREIGN_KEY = FieldTypeDefinition(
    id="ForeignKey",
    icon="fa-solid fa-link",
    model_field_cls=models.ForeignKey,
    label="Foreign Key",
    lookups=(
        lookups.EQUALS,
        lookups.NOT_EQUALS,
        REL_VALUES_IN_LOOKUP,
        lookups.FOREIGN_ADVANCED,
        lookups.IS_NULL,
    ),
    construction=FieldConstruction(
        defaults={"on_delete": models.CASCADE},
        options=(*COMMON_RELATION_FIELD_OPTIONS, ON_DELETE_FIELD_OPTION),
    ),
    widget_factory=relation_widget(),
    form_factory=form(forms.ModelChoiceField, virtual=False),
    render_value=render_foreign_key_dataview_value,
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

ONE_TO_ONE_FIELD = FieldTypeDefinition(
    id="OneToOneField",
    icon="fa-solid fa-link",
    model_field_cls=models.OneToOneField,
    label="One To One Field",
    lookups=(lookups.IS_NULL, lookups.EQUALS, lookups.NOT_EQUALS, REL_VALUES_IN_LOOKUP, lookups.FOREIGN_ADVANCED),
    construction=FieldConstruction(
        defaults={"on_delete": models.CASCADE},
        options=(
            *COMMON_RELATION_FIELD_OPTIONS,
            ON_DELETE_FIELD_OPTION,
            UNIQUE_FIELD_OPTION,
        ),
    ),
    render_value=render_foreign_key_dataview_value,
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

MANY_TO_MANY_FIELD = FieldTypeDefinition(
    id="ManyToManyField",
    icon="fa-solid fa-share-nodes",
    model_field_cls=models.ManyToManyField,
    label="Many To Many Field",
    lookups=(
        lookups.EQUALS, 
        lookups.NOT_EQUALS, 
        lookups.IS_NULL,
        REL_VALUES_IN_LOOKUP, 
        lookups.FOREIGN_ADVANCED
    ),
    construction=FieldConstruction(
        defaults={},
        options=(
            TO_FIELD_OPTION,
            VERBOSE_NAME_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            RELATED_NAME_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
        ),
    ),
    widget_factory=relation_widget(multiple=True),
    render_value=render_m2m_dataview_value,
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

ONE_TO_MANY_FIELD = FieldTypeDefinition(
    id="OneToManyField",
    icon="fa-solid fa-share-nodes",
    label="One To Many Field",
    lookups=tuple(ONE_TO_MANY_LOOKUPS),
    widget_factory=inline_widget,
    form_factory=form(OneToManyField, virtual=True),
    display_options=(
        LABEL_OPTION,
        *[
            FieldDisplayOption(
                id="inline_fields",
                label="Inline fields",
                form_field_cls=OrderedMultipleChoiceField,
                required=False,
                help_text="Choose which related fields appear as editable columns.",
                get_form_field_kwargs=get_related_model_field_choices,
            ),
            FieldDisplayOption(
                id="show_totals",
                label="Show totals",
                form_field_cls=forms.BooleanField,
                required=False,
                default=False,
                help_text="Show totals beneath numeric inline columns.",
            ),
            FieldDisplayOption(
                id="page_size",
                label="Page size",
                form_field_cls=forms.IntegerField,
                required=False,
                default=10,
                help_text="Choose how many related rows appear on each page.",
                form_field_kwargs={"min_value": 1, "max_value": 100},
            ),
        ],
        BEHAVIORS_DISPLAY_OPTION,
    ),
)

USER_FIELD = FieldTypeDefinition(
    id="UserField",
    icon="fa-solid fa-user",
    model_field_cls=UserField,
    label="User Field",
    lookups=(
        lookups.IS_NULL, 
        BoundLookup(
            lookup=lookups.EQUALS_USER,
            
        ), 
        lookups.EQUALS
    ),
    construction=FieldConstruction(
        defaults={},
        options=(
            VERBOSE_NAME_FIELD_OPTION,
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DB_INDEX_FIELD_OPTION,
            RELATED_NAME_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
            ON_DELETE_FIELD_OPTION,
        ),
    ),
    widget_factory=relation_widget(),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

ONE_TO_ONE_USER_FIELD = FieldTypeDefinition(
    id="OneToOneUserField",
    icon="fa-solid fa-user",
    model_field_cls=OneToOneUserField,
    label="One To One User Field",
    lookups=(lookups.IS_NULL, lookups.EQUALS_USER, lookups.EQUALS),
    construction=FieldConstruction(
        defaults={},
        options=(
            VERBOSE_NAME_FIELD_OPTION,
            NULL_FIELD_OPTION,
            BLANK_FIELD_OPTION,
            DB_INDEX_FIELD_OPTION,
            RELATED_NAME_FIELD_OPTION,
            HELP_TEXT_FIELD_OPTION,
            ON_DELETE_FIELD_OPTION,
        ),
    ),
    widget_factory=relation_widget(),
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

GENERIC_RELATION = FieldTypeDefinition(
    id="GenericRelation",
    icon="fa-solid fa-share-nodes",
    label="Generic Relation",
    lookups=(),
    render_value=render_m2m_dataview_value,
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

GENERIC_FOREIGN_KEY = FieldTypeDefinition(
    id="GenericForeignKey",
    icon="fa-solid fa-link",
    label="Generic Foreign Key",
    lookups=(),
    render_value=render_foreign_key_dataview_value,
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)

FILES_RELATION_FIELD = FieldTypeDefinition(
    id="FilesRelationField",
    icon="fa-solid fa-paperclip",
    label="Files",
    lookups=(),
    widget_factory=widget(ObjectFilesWidget, attrs={}),
    form_factory=form(FilesRelationField, virtual=True),
    render_value=render_m2m_dataview_value,
    display_options=(LABEL_OPTION, BEHAVIORS_DISPLAY_OPTION),
)


def register(registry: FieldTypeRegistry) -> None:
    registry.register("FOREIGN_KEY", FOREIGN_KEY)
    registry.register("ONE_TO_ONE_FIELD", ONE_TO_ONE_FIELD)
    registry.register("MANY_TO_MANY_FIELD", MANY_TO_MANY_FIELD)
    registry.register("ONE_TO_MANY_FIELD", ONE_TO_MANY_FIELD)
    registry.register("USER_FIELD", USER_FIELD)
    registry.register("ONE_TO_ONE_USER_FIELD", ONE_TO_ONE_USER_FIELD)
    registry.register("GENERIC_RELATION", GENERIC_RELATION)
    registry.register("GENERIC_FOREIGN_KEY", GENERIC_FOREIGN_KEY)
    registry.register("FILES_RELATION_FIELD", FILES_RELATION_FIELD)

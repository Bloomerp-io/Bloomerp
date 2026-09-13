"""Current-user comparison; permission compilers supply the current user."""
from django import forms
from bloomerp.lookups.definition import LookupDefinition
from bloomerp.lookups.builtins.equals import EQUALS, equals


def equals_user_form_factory(context):
    field = context.get_form_field()
    field.initial = "$user"
    field.widget = forms.HiddenInput(attrs={"value": "$user"})
    return field


EQUALS_USER = LookupDefinition(
    id="equals_user",
    label="Equals Current User",
    expressions=("equals_user",),
    q_factory=EQUALS.q_factory,
    python_evaluator=equals,
    sql_factory=EQUALS.sql_factory,
    default_form_factory=equals_user_form_factory,
)

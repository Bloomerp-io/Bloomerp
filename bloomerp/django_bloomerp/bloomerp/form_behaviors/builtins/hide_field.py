


from bloomerp.form_behaviors.definition import BehaviorActionDefinition


HIDE_FIELD = BehaviorActionDefinition(
    id="hide_field",
    label="Hide field",
    description="Hides a particular field",
    requires_target_field=True,
    transform=lambda widget: (setattr(widget, 'is_hidden', True), widget)[1],
)

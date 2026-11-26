from django.db.models import Model
from django.urls import reverse
from django.utils.translation import gettext_noop

from bloomerp.models.actions.permissions import can_add_model
from bloomerp.models.definition import ObjectAction, ObjectActionContext


def _can_create_todo(context: ObjectActionContext) -> bool:
    """Check whether the requester can add a Todo."""
    from bloomerp.models.project_management.todo import Todo

    return can_add_model(context.request, Todo)


def create_todo_action(model: type[Model]) -> ObjectAction | None:
    """Open the dedicated Todo form for records outside Todo and Initiative."""
    if model._meta.model_name in {"todo", "initiative"}:
        return None
    return ObjectAction(
        id="create-todo",
        label=gettext_noop("Create Todo"),
        icon="fa fa-list-check",
        method="GET",
        endpoint=lambda context: reverse("components_create_todo_for_object", kwargs={
            "content_type_id": context.content_type.pk,
            "object_id": context.object.pk,
        }),
        should_render_func=_can_create_todo,
        button_attrs=lambda context: {
            **({"class": "btn btn-secondary btn-sm"} if context.surface == "detail" else {}),
            "hx-target": "#detail-todo-modal-body",
            "hx-animation": True,
            "hx-push-url": "false",
            "bloomerp-open-modal": "detail-todo-modal",
        },
        shortcut="d then t"
    )

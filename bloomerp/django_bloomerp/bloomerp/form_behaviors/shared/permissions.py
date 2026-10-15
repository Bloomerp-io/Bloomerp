from django.utils.functional import Promise
from django.utils.translation import gettext_lazy as _

from bloomerp.form_behaviors.definition import BehaviorMessage, BehaviorResult


def permission_denied_result(message: str | Promise | None = None) -> BehaviorResult:
    """Return a non-mutating danger message for an action-level access denial."""
    detail = str(_("Permission denied: %(message)s") % {"message": message}) if message else str(_("Permission denied"))
    return BehaviorResult(
        messages=(
            BehaviorMessage(
                type="danger",
                message=detail,
            ),
        )
    )

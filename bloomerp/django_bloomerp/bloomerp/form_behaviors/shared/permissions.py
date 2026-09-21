from bloomerp.form_behaviors.definition import BehaviorMessage, BehaviorResult


def permission_denied_result(message: str | None = None) -> BehaviorResult:
    """Return a non-mutating danger message for an action-level access denial."""
    detail = f"Permission denied: {message}" if message else "Permission denied"
    return BehaviorResult(
        messages=(
            BehaviorMessage(
                type="danger",
                message=detail,
            ),
        )
    )

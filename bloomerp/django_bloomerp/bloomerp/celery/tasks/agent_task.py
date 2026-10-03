"""Execute agent attempts in configured Celery workers using only durable IDs."""

from uuid import UUID, uuid4

from asgiref.sync import async_to_sync
from celery import shared_task
from django.contrib.auth import get_user_model

from bloomerp.agents.controller import AgentController


@shared_task(
    name="bloomerp.agents.execute_run", acks_late=True, reject_on_worker_lost=True
)
def execute_agent_run(run_id: str, user_id: str) -> None:
    """Resolve the current actor and run one fenced attempt in this worker."""
    user = get_user_model().objects.get(pk=user_id)
    async_to_sync(AgentController(user).run_attempt)(
        UUID(run_id),
        execution_mode="worker",
        executor_id=f"worker:{uuid4()}",
    )

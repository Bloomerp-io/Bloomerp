import json
import tempfile
from unittest.mock import Mock, patch

from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError, IntegrityError, models
from django.test import TransactionTestCase
from django_celery_beat.models import PeriodicTask
from regex import F

from bloomerp.automation.run import (
    _execute_node,
    format_execution_trace,
    resume_workflow,
    run_workflow,
    run_workflow_sync,
    serialize_workflow_value,
)
from bloomerp.automation.schema import WorkflowValueType
from bloomerp.automation.schema_resolver import resolve_node_output_schema
from bloomerp.automation.utils import enhanced_get_attr
from bloomerp.automation.workflow_state import WorkflowRunState
from bloomerp.models import ApplicationField, User
from bloomerp.models.automation import Workflow, WorkflowEdge, WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.automation.workflow_run_step import WorkflowRunStep
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.celery.tasks.workflow_task import (
    resume_workflow_async,
    run_scheduled_workflow,
    run_workflow_async,
)
from bloomerp.signals.automation_signals import setup_automation_signals
from bloomerp.tests.utils.dynamic_models import create_test_models, ensure_content_types_for_models
from django.contrib.auth import get_user_model

# TODO: This will change in the future
def get_terminal_node_output(workflow_run:WorkflowRun) -> dict|list|None:
    for trace_entry in reversed(workflow_run.execution_trace):
        if trace_entry["output"] is not None:
            return trace_entry["output"]
    return None


class TestAutomation(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1. Create isolated test model (NOT bloomerp data), but we register the
        # model under the real "bloomerp" app so AUTH_USER_MODEL relations
        # resolve normally and Django can flush tables between tests.
        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": {
                    "first_name": models.CharField(max_length=100),
                    "last_name": models.CharField(max_length=100),
                    "age" : models.IntegerField()
                }
            },
            use_bloomerp_base=True
        )["Customer"]

        cls.EmployeeModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "AutomationEmployee": {
                    "first_name": models.CharField(max_length=100),
                    "last_name": models.CharField(max_length=100, blank=True),
                    "email": models.EmailField(blank=True),
                    "status": models.CharField(max_length=20, default="active"),
                }
            },
            use_bloomerp_base=True,
        )["AutomationEmployee"]
    
    
    def setUp(self):
        super().setUp()
        ensure_content_types_for_models(self.CustomerModel, self.EmployeeModel)
        self.customer_content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.employee_content_type = ContentType.objects.get_for_model(self.EmployeeModel)
        self.customer_age_field, _ = ApplicationField.objects.get_or_create(
            content_type=self.customer_content_type,
            field="age",
            defaults={
                "field_type": "IntegerField",
                "db_table": self.CustomerModel._meta.db_table,
                "db_column": "age",
                "db_field_type": "IntegerField",
            },
        )
        self.user = User.objects.create_user(username="testuser", password="password")
        self.workflow = Workflow.objects.create(
            name="Test Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        
        self.start_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age" : 20
                    }
                },
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        
        self.end_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id" : ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        
        WorkflowEdge.objects.create(
            from_node=self.start_node,
            to_node=self.end_node,
        )
        
    def test_workflow_execution_create_record_human_trigger(self):
        # 1. Create the test data
        data = {
            "first_name" : "John",
            "last_name"  : "Doe",
        }
        
        # 2. Run the workflow
        self.workflow.enable_logging = True
        self.workflow.save(update_fields=["enable_logging"])
        workflow_run = run_workflow(self.workflow, data)

        # 3. Check the result
        qs = self.CustomerModel.objects.filter(
            first_name="John",
            last_name="Doe"
        )
        self.assertTrue(qs.exists())
        self.assertEqual(
            [
                entry["node_sub_type"]
                for entry in workflow_run.execution_trace
            ],
            ["HUMAN_TRIGGER", "CREATE_OBJECT"],
        )
        self.assertTrue(
            all(entry["status"] == "success" for entry in workflow_run.execution_trace)
        )
        self.assertIn(
            "HUMAN_TRIGGER: success",
            format_execution_trace(workflow_run.execution_trace),
        )
        steps = list(workflow_run.steps.order_by("sequence"))
        self.assertEqual([step.sequence for step in steps], [0, 1])
        self.assertEqual([step.action_id for step in steps], ["HUMAN_TRIGGER", "CREATE_OBJECT"])
        self.assertEqual([step.status for step in steps], ["COMPLETED", "COMPLETED"])

    def test_workflow_execution_skips_step_rows_when_logging_disabled(self):
        self.workflow.enable_logging = False
        self.workflow.save(update_fields=["enable_logging"])

        workflow_run = run_workflow(self.workflow, {"first_name": "John"})

        self.assertEqual(workflow_run.steps.count(), 0)
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "CREATE_OBJECT"],
        )

    def test_logged_steps_store_state_and_node_outputs(self):
        workflow = Workflow.objects.create(name="Checkpoint workflow", enable_logging=True)
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"run": True}},
            type="TRIGGER",
        )
        enrich = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"amount": 100}},
            type="ACTION",
        )
        workflow.connect_nodes(trigger, enrich)

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            workflow_run = run_workflow(workflow, {"employee_id": 7})
            steps = list(workflow_run.steps.order_by("sequence"))

            self.assertEqual(len(steps), 2)
            for step in steps:
                state = WorkflowRunState.model_validate(step.state)
                self.assertEqual(state.workflow_run_id, workflow_run.id)
                self.assertEqual(state.current_step_id, step.id)
                self.assertTrue(step.output_file)

            with steps[0].output_file.open("r") as output_file:
                self.assertEqual(
                    json.load(output_file),
                    {"run": True, "employee_id": 7},
                )
            with steps[1].output_file.open("r") as output_file:
                self.assertEqual(
                    json.load(output_file),
                    {"run": True, "employee_id": 7, "amount": 100},
                )

    def test_resume_workflow_continues_existing_run_from_saved_step(self):
        workflow = Workflow.objects.create(name="Resume workflow", enable_logging=True)
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"run": True}},
            type="TRIGGER",
        )
        pause_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"proposal": "ready"}},
            type="ACTION",
        )
        workflow.connect_nodes(trigger, pause_node)

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            workflow_run = run_workflow(workflow, {"employee_id": 7})
            paused_step = workflow_run.steps.get(sequence=1)
            paused_step.status = "PAUSED"
            paused_step.save(update_fields=["status"])

            downstream = WorkflowNode.objects.create(
                workflow=workflow,
                sub_type="ENRICH_DATA",
                parameters={"data": {"approved": True}},
                type="ACTION",
            )
            workflow.connect_nodes(pause_node, downstream)

            resumed_run = resume_workflow(paused_step)

            self.assertEqual(resumed_run.id, workflow_run.id)
            self.assertEqual(
                [step.sequence for step in resumed_run.steps.order_by("sequence")],
                [0, 1, 2],
            )
            self.assertEqual(resumed_run.execution_trace[0]["output"]["proposal"], "ready")
            self.assertTrue(resumed_run.execution_trace[0]["output"]["approved"])

    def test_resume_workflow_dispatches_asynchronously_for_async_workflow(self):
        workflow = Workflow.objects.create(name="Async resume workflow", enable_logging=True)
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"proposal": "ready"}},
            type="TRIGGER",
        )
        pause_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {}},
            type="ACTION",
        )
        workflow.connect_nodes(trigger, pause_node)

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            workflow_run = run_workflow(workflow, {})
            paused_step = workflow_run.steps.get(sequence=1)
            paused_step.status = "PAUSED"
            paused_step.save(update_fields=["status"])
            workflow.run_asynchronously = True
            workflow.save(update_fields=["run_asynchronously"])

            with patch(
                "bloomerp.automation.run.resume_workflow_async.delay"
            ) as delay_mock:
                result = resume_workflow(paused_step)

            self.assertIsNone(result)
            delay_mock.assert_called_once_with(paused_step.pk)
            paused_step.refresh_from_db()
            self.assertEqual(paused_step.status, "PAUSED")

    def _create_resumable_workflow(
        self,
        *,
        run_asynchronously: bool = False,
    ) -> tuple[WorkflowRun, WorkflowRunStep]:
        """Create a workflow run with one paused step and one downstream node."""
        workflow = Workflow.objects.create(
            name="Resume transaction boundary",
            enable_logging=True,
            run_asynchronously=run_asynchronously,
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"proposal": "ready"}},
            type="TRIGGER",
        )
        pause_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {}},
            type="ACTION",
        )
        workflow.connect_nodes(trigger, pause_node)

        workflow_run = run_workflow_sync(workflow, {})
        paused_step = workflow_run.steps.get(sequence=1)
        paused_step.status = "PAUSED"
        paused_step.save(update_fields=["status"])

        downstream = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"approved": True}},
            type="ACTION",
        )
        workflow.connect_nodes(pause_node, downstream)
        return workflow_run, paused_step

    def test_resume_workflow_recovers_from_handled_database_error(self):
        """
        Use case: A resumed node handles a database error as workflow output.
        Expected result: The workflow records that output without breaking its resume transaction.
        """
        # 1. Create a workflow run with a step that can be resumed.
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            _workflow_run, paused_step = self._create_resumable_workflow()

            # 2. Simulate an executor that handles a database constraint error.
            def handle_database_error(_node, _input_data):
                try:
                    User.objects.create(username=self.user.username)
                except IntegrityError as error:
                    return {
                        "status": "error",
                        "error_message": str(error),
                    }

            with patch.object(WorkflowNode, "execute", new=handle_database_error):
                # 3. Resume the workflow without poisoning its outer transaction.
                resumed_run = resume_workflow(paused_step)

            # 4. Verify the handled error and completed resume are persisted.
            paused_step.refresh_from_db()
            self.assertEqual(paused_step.status, "COMPLETED")
            self.assertEqual(
                resumed_run.execution_trace[-1]["output"]["status"],
                "error",
            )

    def test_execute_node_recovers_output_after_aborted_savepoint(self):
        """
        Use case: PostgreSQL detects a swallowed database error when committing a savepoint.
        Expected result: Explicit error output is preserved after the savepoint is rolled back.
        """
        # 1. Simulate an executor returning an explicit error before savepoint release fails.
        node = Mock()
        node.execute.return_value = {
            "status": "error",
            "error_message": "Invalid configured query",
        }
        connection = Mock(in_atomic_block=True)
        postgres_error = Exception("current transaction is aborted")
        postgres_error.sqlstate = "25P02"
        aborted_transaction = DatabaseError("current transaction is aborted")
        aborted_transaction.__cause__ = postgres_error

        class AbortedSavepoint:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                raise aborted_transaction

        # 2. Execute through the failed savepoint boundary reported by PostgreSQL.
        with (
            patch(
                "bloomerp.automation.run.transaction.get_connection",
                return_value=connection,
            ),
            patch(
                "bloomerp.automation.run.transaction.atomic",
                return_value=AbortedSavepoint(),
            ),
        ):
            output = _execute_node(node, {})

        # 3. Verify the executor's handled error remains available to the workflow.
        self.assertEqual(output["status"], "error")
        self.assertEqual(output["error_message"], "Invalid configured query")

    def test_execute_node_reraises_unrelated_savepoint_database_error(self):
        """
        Use case: Savepoint release fails for a reason unrelated to an aborted transaction.
        Expected result: The database failure is not hidden by an executor error result.
        """
        # 1. Simulate an executor error result followed by an unrelated connection failure.
        node = Mock()
        node.execute.return_value = {
            "status": "error",
            "error_message": "Invalid configured query",
        }
        connection = Mock(in_atomic_block=True)
        connection_error = DatabaseError("server closed the connection unexpectedly")

        class FailedSavepoint:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                raise connection_error

        # 2. Verify that only PostgreSQL's aborted-transaction error is recoverable.
        with (
            patch(
                "bloomerp.automation.run.transaction.get_connection",
                return_value=connection,
            ),
            patch(
                "bloomerp.automation.run.transaction.atomic",
                return_value=FailedSavepoint(),
            ),
            self.assertRaises(DatabaseError) as raised,
        ):
            _execute_node(node, {})

        self.assertIs(raised.exception, connection_error)

    def test_async_resume_recovers_from_handled_database_error(self):
        """
        Use case: Celery resumes a node that handles a database error as workflow output.
        Expected result: The task completes without breaking the workflow resume transaction.
        """
        # 1. Create an asynchronous workflow run with a step that can be resumed.
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            workflow_run, paused_step = self._create_resumable_workflow(
                run_asynchronously=True,
            )

            # 2. Simulate an executor that handles a database constraint error.
            def handle_database_error(_node, _input_data):
                try:
                    User.objects.create(username=self.user.username)
                except IntegrityError as error:
                    return {
                        "status": "error",
                        "error_message": str(error),
                    }

            with patch.object(WorkflowNode, "execute", new=handle_database_error):
                # 3. Run the Celery task directly.
                result = resume_workflow_async.run(paused_step.pk)

            # 4. Verify the async resume completed and persisted its handled error.
            paused_step.refresh_from_db()
            completed_step = workflow_run.steps.order_by("-sequence").first()
            self.assertEqual(paused_step.status, "COMPLETED")
            self.assertEqual(completed_step.status, "COMPLETED")
            with completed_step.output_file.open("r") as output_file:
                self.assertEqual(json.load(output_file)["status"], "error")
            self.assertEqual(result["workflow_run_id"], str(workflow_run.id))

    def test_resume_workflow_rolls_back_completion_after_unhandled_error(self):
        """
        Use case: A downstream node raises while a paused workflow is being resumed.
        Expected result: The paused step remains retryable and no successor step is committed.
        """
        # 1. Create a workflow run with a step that can be resumed.
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            workflow_run, paused_step = self._create_resumable_workflow()

            # 2. Fail the downstream executor during the resume transaction.
            with patch.object(
                WorkflowNode,
                "execute",
                side_effect=ValueError("Downstream execution failed"),
            ):
                with self.assertRaisesRegex(ValueError, "Downstream execution failed"):
                    resume_workflow(paused_step)

            # 3. Verify the completion and failed successor step were rolled back.
            paused_step.refresh_from_db()
            self.assertEqual(paused_step.status, "PAUSED")
            self.assertEqual(workflow_run.steps.count(), 2)

    def test_run_workflow_can_start_from_a_selected_node(self):
        workflow = Workflow.objects.create(name="Debug start workflow")
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"trigger_ran": True}},
            type="TRIGGER",
        )
        start_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"started_here": True}},
            type="ACTION",
        )

        workflow_run = run_workflow(
            workflow,
            {"debug_input": True},
            start_node=start_node,
        )

        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["ENRICH_DATA"],
        )
        self.assertTrue(workflow_run.execution_trace[0]["output"]["debug_input"])
        self.assertTrue(workflow_run.execution_trace[0]["output"]["started_here"])
    
    def test_workflow_execution_create_record_human_trigger_empty_data(self):
        # 1. Create the test data
        data = {}
        
        # 2. Run the workflow
        run_workflow(self.workflow, data)
    
        # 3. Check the result
        qs = self.CustomerModel.objects.filter(
            first_name="John",
            last_name="Doe"
        )
        self.assertTrue(qs.exists())

    def test_run_workflow_queues_celery_task_when_workflow_is_async(self):
        self.workflow.run_asynchronously = True
        self.workflow.save(update_fields=["run_asynchronously"])

        with patch("bloomerp.automation.run.run_workflow_async.delay") as delay_mock:
            result = run_workflow(self.workflow, {"first_name": "John"})

        self.assertIsNone(result)
        delay_mock.assert_called_once_with(
            self.workflow.id,
            {"first_name": "John"},
        )

    def test_async_workflow_passes_selected_start_node_to_celery(self):
        self.workflow.run_asynchronously = True
        self.workflow.save(update_fields=["run_asynchronously"])

        with patch("bloomerp.automation.run.run_workflow_async.delay") as delay_mock:
            result = run_workflow(
                self.workflow,
                {"first_name": "John"},
                start_node=self.end_node,
            )

        self.assertIsNone(result)
        delay_mock.assert_called_once_with(
            self.workflow.id,
            {"first_name": "John"},
            self.end_node.id,
        )

    def test_run_workflow_skips_a_workflow_deactivated_in_the_database(self):
        """
        Use case: A caller holds an active workflow instance after it is deactivated elsewhere.
        Expected result: The workflow is not queued or executed from stale in-memory state.
        """
        # 1. Configure asynchronous execution and retain the active model instance.
        self.workflow.run_asynchronously = True
        self.workflow.save(update_fields=["run_asynchronously"])
        Workflow.objects.filter(pk=self.workflow.pk).update(active=False)

        # 2. Attempt dispatch with the stale instance and verify nothing is queued.
        with patch("bloomerp.automation.run.run_workflow_async.delay") as delay_mock:
            result = run_workflow(self.workflow, {"first_name": "John"})

        self.assertIsNone(result)
        delay_mock.assert_not_called()

    def test_run_workflow_sync_skips_a_workflow_deactivated_in_the_database(self):
        """
        Use case: A direct synchronous caller holds stale active workflow state.
        Expected result: No workflow run is created after database deactivation.
        """
        # 1. Deactivate the workflow without updating the in-memory instance.
        Workflow.objects.filter(pk=self.workflow.pk).update(active=False)

        # 2. Attempt synchronous execution and verify no run is persisted.
        result = run_workflow_sync(self.workflow, {"first_name": "John"})

        self.assertIsNone(result)
        self.assertFalse(WorkflowRun.objects.filter(workflow=self.workflow).exists())

    def test_run_workflow_async_hydrates_model_instances_before_running_sync(self):
        workflow = Workflow.objects.create(
            name="Async employee workflow",
            run_asynchronously=True,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_CREATE",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.EmployeeModel).id,
                },
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )

        with patch("bloomerp.automation.run.run_workflow_async.delay"):
            employee = self.EmployeeModel.objects.create(
                first_name="Ava",
                last_name="Ng",
                email="ava@example.com",
                created_by=self.user,
                updated_by=self.user,
            )
        serialized_trigger_data = serialize_workflow_value(
            {
                "event": "create",
                "sender": self.EmployeeModel,
                "instance": employee,
                "data": {"created": True},
            }
        )

        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            run_workflow_async(workflow.id, serialized_trigger_data)

        run_workflow_sync_mock.assert_called_once()
        called_workflow, called_trigger_data = run_workflow_sync_mock.call_args[0]
        self.assertEqual(called_workflow.id, workflow.id)
        self.assertIsInstance(called_trigger_data["instance"], self.EmployeeModel)
        self.assertEqual(called_trigger_data["instance"].id, employee.id)
        self.assertEqual(called_trigger_data["sender"], self.EmployeeModel)

    def test_run_workflow_async_returns_json_safe_result(self):
        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            workflow_run = WorkflowRun(id=123)
            run_workflow_sync_mock.return_value = workflow_run

            result = run_workflow_async(self.workflow.id, {"first_name": "John"})

        self.assertEqual(result, {"workflow_run_id": "123"})

    def test_run_workflow_async_skips_a_workflow_deactivated_after_queueing(self):
        """
        Use case: An asynchronous workflow is deactivated after its task is queued.
        Expected result: The worker drops the task before synchronous execution.
        """
        # 1. Simulate deactivation after a task has already captured the workflow id.
        workflow_id = self.workflow.id
        self.workflow.active = False
        self.workflow.save(update_fields=["active"])

        # 2. Run the queued task and verify it does not enter the workflow engine.
        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            result = run_workflow_async(workflow_id, {"first_name": "John"})

        self.assertIsNone(result)
        run_workflow_sync_mock.assert_not_called()

    # ----------------------------------------
    # Trigger: SCHEDULE
    # ----------------------------------------
    def test_trigger_schedule_trigger_syncs_celery_beat_task(self):
        workflow = Workflow.objects.create(
            name="Scheduled workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="SCHEDULE",
            parameters={
                    "schedule": "*/5 * * * *",
                    "timezone": "Europe/Brussels",
                },
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )

        task = PeriodicTask.objects.get(name=f"bloomerp.workflow.schedule.{workflow.id}")
        self.assertEqual(task.task, "bloomerp.celery.tasks.workflow_task.run_scheduled_workflow")
        self.assertEqual(task.args, f"[{workflow.id}]")
        self.assertTrue(task.enabled)
        self.assertEqual(task.crontab.minute, "*/5")
        self.assertEqual(str(task.crontab.timezone), "Europe/Brussels")

        workflow.active = False
        workflow.save(update_fields=["active"])
        task.refresh_from_db()
        self.assertFalse(task.enabled)

        trigger.parameters["schedule"] = ""
        trigger.save(update_fields=["parameters"])
        self.assertFalse(
            PeriodicTask.objects.filter(name=f"bloomerp.workflow.schedule.{workflow.id}").exists()
        )

    def test_run_scheduled_workflow_returns_json_safe_result(self):
        workflow = Workflow.objects.create(
            name="Scheduled workflow result",
            created_by=self.user,
            updated_by=self.user,
        )

        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            workflow_run = WorkflowRun(id=456)
            run_workflow_sync_mock.return_value = workflow_run

            result = run_scheduled_workflow(workflow.id)

        self.assertEqual(result, {"workflow_run_id": "456"})

    # ----------------------------------------
    # Trigger: ON_OBJECT_CREATE, ON_OBJECT_UPDATE, ON_OBJECT_DELETE
    # ----------------------------------------
    def test_run_workflow_called_after_create(self):
        """
        Ensures workflow runs when an object is created with a matching trigger.
        """
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Create Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_CREATE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )

        setup_automation_signals(refresh=True)

        with patch("bloomerp.signals.automation_signals.run_workflow") as run_workflow_mock:
            self.CustomerModel.objects.create(
                first_name="Jane",
                last_name="Doe",
                age=30,
                created_by=self.user,
                updated_by=self.user,
            )

            run_workflow_mock.assert_called_once()
        
    def test_run_workflow_called_after_delete(self):
        """
        Ensures workflow runs when an object is deleted with a matching trigger.
        """
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Delete Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_DELETE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )

        setup_automation_signals(refresh=True)

        instance = self.CustomerModel.objects.create(
            first_name="Jake",
            last_name="Doe",
            age=40,
            created_by=self.user,
            updated_by=self.user,
        )

        with patch("bloomerp.signals.automation_signals.run_workflow") as run_workflow_mock:
            instance.delete()
            run_workflow_mock.assert_called_once()
        
    def test_run_workflow_called_after_update(self):
        """
        Ensures workflow runs when an object is updated with a matching trigger.
        """
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Update Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_UPDATE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )

        setup_automation_signals(refresh=True)

        instance = self.CustomerModel.objects.create(
            first_name="Jill",
            last_name="Doe",
            age=22,
            created_by=self.user,
            updated_by=self.user,
        )

        with patch("bloomerp.signals.automation_signals.run_workflow") as run_workflow_mock:
            instance.age = 23
            instance.updated_by = self.user
            instance.save()

            run_workflow_mock.assert_called_once()

    def test_run_workflow_called_after_create_or_update(self):
        """
        Use case: A workflow has a combined object create-or-update trigger.
        Expected result: The workflow runs once for both a create and an update.
        """
        # 1. Create a workflow with a combined post-save trigger.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Create Or Update Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_CREATE_OR_UPDATE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        setup_automation_signals(refresh=True)

        # 2. Verify the combined trigger handles object creation.
        with patch("bloomerp.signals.automation_signals.run_workflow") as run_workflow_mock:
            instance = self.CustomerModel.objects.create(
                first_name="Create",
                last_name="Or Update",
                age=30,
                created_by=self.user,
                updated_by=self.user,
            )

            run_workflow_mock.assert_called_once()
            self.assertEqual(run_workflow_mock.call_args.args[1]["event"], "create")

        # 3. Verify the same trigger handles object updates.
        with patch("bloomerp.signals.automation_signals.run_workflow") as run_workflow_mock:
            instance.age = 31
            instance.updated_by = self.user
            instance.save()

            run_workflow_mock.assert_called_once()
            self.assertEqual(run_workflow_mock.call_args.args[1]["event"], "update")

    def test_deactivated_workflow_does_not_run_after_create(self):
        """
        Use case: An active object-create workflow is deactivated after signal registration.
        Expected result: Creating the matching object does not run the deactivated workflow.
        """
        # 1. Register an active workflow with a matching object-create trigger.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Deactivated Create Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_CREATE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        setup_automation_signals(refresh=True)
        workflow.active = False
        workflow.save(update_fields=["active"])

        # 2. Create the matching object and verify execution is skipped at runtime.
        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            self.CustomerModel.objects.create(
                first_name="Deactivated",
                last_name="Create",
                age=30,
                created_by=self.user,
                updated_by=self.user,
            )

        run_workflow_sync_mock.assert_not_called()

    def test_deactivated_workflow_does_not_run_after_update(self):
        """
        Use case: An active object-update workflow is deactivated after signal registration.
        Expected result: Updating the matching object does not run the deactivated workflow.
        """
        # 1. Register an active workflow with a matching object-update trigger.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Deactivated Update Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_UPDATE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        setup_automation_signals(refresh=True)
        instance = self.CustomerModel.objects.create(
            first_name="Deactivated",
            last_name="Update",
            age=30,
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.active = False
        workflow.save(update_fields=["active"])

        # 2. Update the matching object and verify execution is skipped at runtime.
        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            instance.age = 31
            instance.updated_by = self.user
            instance.save()

        run_workflow_sync_mock.assert_not_called()

    def test_deactivated_workflow_does_not_run_after_delete(self):
        """
        Use case: An active object-delete workflow is deactivated after signal registration.
        Expected result: Deleting the matching object does not run the deactivated workflow.
        """
        # 1. Register an active workflow with a matching object-delete trigger.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Deactivated Delete Trigger Workflow",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_DELETE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        setup_automation_signals(refresh=True)
        instance = self.CustomerModel.objects.create(
            first_name="Deactivated",
            last_name="Delete",
            age=30,
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.active = False
        workflow.save(update_fields=["active"])

        # 2. Delete the matching object and verify execution is skipped at runtime.
        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            instance.delete()

        run_workflow_sync_mock.assert_not_called()

    def test_reactivated_workflow_runs_without_signal_refresh(self):
        """
        Use case: An inactive object-create workflow is registered and later activated.
        Expected result: It starts running without rebuilding process-local signal handlers.
        """
        # 1. Register an inactive workflow with a matching object-create trigger.
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        workflow = Workflow.objects.create(
            name="Reactivated Create Trigger Workflow",
            active=False,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ON_OBJECT_CREATE",
            parameters={"content_type_id": content_type.id},
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        setup_automation_signals(refresh=True)

        # 2. Verify it is skipped while inactive, then activate it without refreshing signals.
        with patch("bloomerp.automation.run.run_workflow_sync") as run_workflow_sync_mock:
            self.CustomerModel.objects.create(
                first_name="Before",
                last_name="Activation",
                age=30,
                created_by=self.user,
                updated_by=self.user,
            )
            run_workflow_sync_mock.assert_not_called()

            workflow.active = True
            workflow.save(update_fields=["active"])
            self.CustomerModel.objects.create(
                first_name="After",
                last_name="Activation",
                age=31,
                created_by=self.user,
                updated_by=self.user,
            )

        run_workflow_sync_mock.assert_called_once()
    
    def test_exeucte_node(self):
        """Tests the execution of a basic node"""
        data = self.start_node.execute({}) # Don't need to pass any data with human triggers
        
        self.assertEqual(self.start_node.parameters.get("data"), data)

    # ----------------------------------------
    # Flow: IF_CONDITION
    # ----------------------------------------
    def test_if_condition_continues_when_condition_matches(self):
        self.end_node.delete()
        if_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "exact",
                    "value": "20",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=self.start_node, to_node=if_node)
        WorkflowEdge.objects.create(
            from_node=if_node,
            to_node=create_node,
            output_port="true",
        )

        workflow_run = run_workflow(self.workflow, {})

        self.assertTrue(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION", "CREATE_OBJECT"],
        )

    def test_if_condition_stops_branch_when_condition_does_not_match(self):
        self.end_node.delete()
        if_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "exact",
                    "value": "99",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=self.start_node, to_node=if_node)
        WorkflowEdge.objects.create(
            from_node=if_node,
            to_node=create_node,
            output_port="true",
        )

        workflow_run = run_workflow(self.workflow, {})

        self.assertFalse(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION"],
        )
        self.assertEqual(
            workflow_run.execution_trace[-1]["route"]["port_id"],
            "false",
        )

    def test_if_condition_greater_than_operator(self):
        """
        UC: User wants to check if a field value is greater than a specified value
        Expected results: The workflow should continue if the condition is met, and stop if not.
        """
        workflow = Workflow.objects.create(name="If Condition Greater Than Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age": 20,
                    },
                },
            type="TRIGGER",
        )
        
        if_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "greater_than",
                    "value": "18",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.connect_nodes(trigger, if_node)
        workflow.connect_nodes(if_node, create_node, output_port="true")

        workflow_run = run_workflow(workflow, {"age": 20})

        self.assertTrue(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION", "CREATE_OBJECT"],
        )
    
    def test_if_condition_less_than_operator(self):
        """
        UC: User wants to check if a field value is less than a specified value
        Expected results: The workflow should continue if the condition is met, and stop if not.
        """
        workflow = Workflow.objects.create(name="If Condition Less Than Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age": 25,
                    },
                },
            type="TRIGGER",
        )
        
        if_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "less_than",
                    "value": "30",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.connect_nodes(trigger, if_node)
        workflow.connect_nodes(if_node, create_node, output_port="true")

        workflow_run = run_workflow(workflow, {"age": 25})

        self.assertTrue(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION", "CREATE_OBJECT"],
        )
    
    def test_if_condition_greater_than_or_equal_operator(self):
        """
        UC: User wants to check if a field value is greater than or equal to a specified value
        Expected results: The workflow should continue if the condition is met, and stop if not.
        """
        workflow = Workflow.objects.create(name="If Condition Greater Than Or Equal Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age": 18,
                    },
                },
            type="TRIGGER",
        )
        
        if_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "greater_than_or_equal",
                    "value": "18",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.connect_nodes(trigger, if_node)
        workflow.connect_nodes(if_node, create_node, output_port="true")

        workflow_run = run_workflow(workflow, {"age": 18})

        self.assertTrue(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION", "CREATE_OBJECT"],
        )
    
    def test_if_condition_less_than_or_equal_operator(self):
        """
        UC: User wants to check if a field value is less than or equal to a specified value
        Expected results: The workflow should continue if the condition is met, and stop if not.
        """
        workflow = Workflow.objects.create(name="If Condition Less Than Or Equal Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age": 30,
                    },
                },
            type="TRIGGER",
        )
        
        if_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "less_than_or_equal",
                    "value": "30",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.connect_nodes(trigger, if_node)
        workflow.connect_nodes(if_node, create_node, output_port="true")

        workflow_run = run_workflow(workflow, {"age": 30})

        self.assertTrue(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION", "CREATE_OBJECT"],
        )
    
    def test_if_condition_with_gt_lt_gte_lte_operator_and_non_numeric_values(self):
        """
        UC: User wants to check if a field value is greater than, less than, greater than or equal to, or less than or equal to a specified value, but the values are non-numeric.
        Expected results: The workflow should return False for the condition check, and the branch should stop.
        """
        workflow = Workflow.objects.create(name="If Condition Non-Numeric Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age": 20,
                    },
                },
            type="TRIGGER",
        )
        
        if_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "name",
                    "operator": "greater_than",
                    "value": "Alice",
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.connect_nodes(trigger, if_node)
        workflow.connect_nodes(if_node, create_node, output_port="true")

        workflow_run = run_workflow(workflow, {"name": "Bob"})

        self.assertFalse(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION"],
        )
    
    def test_if_condition_with_gt_lt_gte_lte_with_float_and_integer_values(self):
        """
        UC: User wants to check if a field value is greater than, less than, greater than or equal to, or less than or equal to a specified value, and the values are float and integer.
        Expected results: The workflow should correctly evaluate the condition and continue or stop the branch accordingly.
        """
        workflow = Workflow.objects.create(name="If Condition Float and Integer Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age": 80,
                    },
                },
            type="TRIGGER",
        )
        
        if_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "age",
                    "operator": "greater_than",
                    "value": 75.5,
                },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        workflow.connect_nodes(trigger, if_node)
        workflow.connect_nodes(if_node, create_node, output_port="true")

        workflow_run = run_workflow(workflow, {"age": 80})

        self.assertTrue(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION", "CREATE_OBJECT"],
        )
    
    def test_if_condition_using_extracted_count_from_queryset(self):
        """
        UC: A user wants to use the extracted count in a queryset

        Expected Result: the count works for the if condition
        """
        # 0. Create some test customers
        self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)

        # 1. Create workflow
        workflow = Workflow.objects.create(name="Test", enable_logging=True)
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"run": True}},
            type="TRIGGER",
        )

        # 2. Create the list objects node
        list_objects_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="LIST_OBJECTS",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            type="ACTION",
        )
        workflow.connect_nodes(trigger, list_objects_node)

        # 3. Create the extract count node
        extract_count_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="EXTRACT_FIELD",
            parameters={"field_path": "input.count"},
            type="ACTION",
        )

        # 4. Create the if condition node
        if_condition_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="IF_CONDITION",
            parameters={
                    "field": "input",
                    "operator": "greater_than",
                    "value": "0",
                },
            type="FLOW",
        )
        workflow.connect_nodes(list_objects_node, extract_count_node)
        workflow.connect_nodes(extract_count_node, if_condition_node)

        # 5. Create a pass-through node that accepts the primitive count
        downstream_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="WAIT",
            parameters={"wait_time": 0},
            type="ACTION",
        )
        workflow.connect_nodes(
            if_condition_node,
            downstream_node,
            output_port="true",
        )

        # 6. Run the workflow
        workflow_run = run_workflow(workflow, {})

        self.assertEqual(workflow_run.number_of_steps, 5)

    # ----------------------------------------
    # Flow: MERGE_BRANCHES
    # ----------------------------------------
    def test_merge_branches_waits_for_all_upstream_nodes_then_runs_downstream_once(self):
        workflow = Workflow.objects.create(name="Merge branches workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"run": True}},
            type="TRIGGER",
        )
        left_branch = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"left_value": "left"}},
            type="ACTION",
        )
        right_branch = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"right_value": "right"}},
            type="ACTION",
        )
        merge_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="MERGE_BRANCHES",
            parameters={},
            type="FLOW",
        )
        tail_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={
                    "data": {
                        "left": f"{{{{ input.node_{left_branch.id}.left_value }}}}",
                        "right": f"{{{{ input.node_{right_branch.id}.right_value }}}}",
                    }
                },
            type="ACTION",
        )

        WorkflowEdge.objects.create(from_node=trigger, to_node=left_branch)
        WorkflowEdge.objects.create(from_node=trigger, to_node=right_branch)
        WorkflowEdge.objects.create(from_node=left_branch, to_node=merge_node)
        WorkflowEdge.objects.create(from_node=right_branch, to_node=merge_node)
        WorkflowEdge.objects.create(from_node=merge_node, to_node=tail_node)

        workflow_run = run_workflow(workflow, {})

        self.assertEqual(get_terminal_node_output(workflow_run)["left"], "left")
        self.assertEqual(get_terminal_node_output(workflow_run)["right"], "right")

        merge_entries = [
            entry
            for entry in workflow_run.execution_trace
            if entry["node_sub_type"] == "MERGE_BRANCHES"
        ]
        self.assertEqual(len(merge_entries), 2)
        self.assertEqual(merge_entries[0]["output"]["kind"], "waiting_for_branches")
        self.assertEqual(merge_entries[1]["output_summary"]["kind"], "object")

    def test_merge_branches_scopes_wait_state_per_for_each_item(self):
        workflow = Workflow.objects.create(name="Merge branches in loop workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "records": [
                            {"value": "A"},
                            {"value": "B"},
                        ]
                    }
                },
            type="TRIGGER",
        )
        for_each_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="FOR_EACH",
            parameters={},
            type="FLOW",
        )
        left_branch = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"left_value": "{{ input.item.value }}-L"}},
            type="ACTION",
        )
        right_branch = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"right_value": "{{ input.item.value }}-R"}},
            type="ACTION",
        )
        merge_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="MERGE_BRANCHES",
            parameters={},
            type="FLOW",
        )
        tail_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={
                    "data": {
                        "combined": (
                            f"{{{{ input.node_{left_branch.id}.left_value }}}}|"
                            f"{{{{ input.node_{right_branch.id}.right_value }}}}"
                        ),
                    }
                },
            type="ACTION",
        )

        WorkflowEdge.objects.create(from_node=trigger, to_node=for_each_node)
        WorkflowEdge.objects.create(from_node=for_each_node, to_node=left_branch)
        WorkflowEdge.objects.create(from_node=for_each_node, to_node=right_branch)
        WorkflowEdge.objects.create(from_node=left_branch, to_node=merge_node)
        WorkflowEdge.objects.create(from_node=right_branch, to_node=merge_node)
        WorkflowEdge.objects.create(from_node=merge_node, to_node=tail_node)

        workflow_run = run_workflow(workflow, {})

        tail_outputs = [
            entry["output"]["combined"]
            for entry in workflow_run.execution_trace
            if entry["node_id"] == tail_node.id
        ]
        self.assertEqual(tail_outputs, ["A-L|A-R", "B-L|B-R"])

    def test_merge_branches_with_fanout(self):
        workflow = Workflow.objects.create(name="Merge branches with fanout workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={
                    "data": {
                        "records": [
                            {"value": "A"},
                            {"value": "B"},
                        ]
                    }
                },
            type="TRIGGER",
        )
        extract_records = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="EXTRACT_FIELD",
            parameters={"field_path": "records"},
            type="ACTION",
        )
        for_each_node = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="FOR_EACH",
            parameters={},
            type="FLOW",
        )
        merge_branch = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="MERGE_BRANCHES",
            parameters={},
            type="FLOW",
        )
        send_message = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="SEND_USER_MESSAGE",
            parameters={
                    "user_id": str(self.user.id),
                    "message": (
                        f"{{{{ input.node_{trigger.id}.records.0.value }}}}|"
                        f"{{{{ input.node_{for_each_node.id}.item.value }}}}"
                    ),
                    "message_type": "success",
                },
            type="ACTION",
        )

        workflow.connect_nodes(trigger, extract_records)
        workflow.connect_nodes(extract_records, for_each_node)
        workflow.connect_nodes(for_each_node, merge_branch)
        workflow.connect_nodes(trigger, merge_branch)
        workflow.connect_nodes(merge_branch, send_message)

        with patch("bloomerp.automation.actions.send_user_message.publish_event") as send_message_mock:
            workflow_run = run_workflow(workflow, {})

        self.assertEqual(send_message_mock.call_count, 2)
        messages = [
            call.kwargs["data"]["message"]
            for call in send_message_mock.call_args_list
        ]
        self.assertEqual(messages, ["A|A", "A|B"])

        send_message_entries = [
            entry
            for entry in workflow_run.execution_trace
            if entry["node_sub_type"] == "SEND_USER_MESSAGE"
        ]
        self.assertEqual(len(send_message_entries), 2)
        
    
    # ----------------------------------------
    # Flow: OBJECT_IF_CONDITION
    # ----------------------------------------
    def test_flow_object_if_condition_continues_when_condition_matches(self):
        # 1. Create an object that matches the condition
        customer = self.CustomerModel.objects.create(first_name="John", last_name="Doe", age=20)
        
        # 2. Create the workflow
        workflow = Workflow.objects.create(name="Object If Condition Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {
                    "id": str(customer.id),
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "age": customer.age,  
                }},
            type="TRIGGER",
        )
        
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="EXTRACT_FIELD",
            parameters={
                    "field_path": "data"
                },
            type="ACTION",
        )
        
        object_if_condition = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="OBJECT_IF_CONDITION",
            parameters={
                    "content_type_id": self.customer_content_type.id,
                    "field": self.customer_age_field.id,
                    "lookup": "equals",
                    "value": "20",
                },
            type="FLOW",
        )
        create_action = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "data": {
                        "first_name": "Jane",
                        "last_name": "Smith",
                        "age": 30,
                    }
                },
            type="ACTION",
        )
        
        workflow.connect_nodes(trigger, object_if_condition)
        
        # 3. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        # 4. Check that the branch continued and returned the original object input.
        self.assertEqual(get_terminal_node_output(workflow_run)["id"], str(customer.id))
        
    def test_flow_object_if_condition_stops_branch_when_condition_does_not_match(self):
        # 1. Create an object that does not match the condition
        customer = self.CustomerModel.objects.create(first_name="John", last_name="Doe", age=20)
        
        # 2. Create the workflow        
        workflow = Workflow.objects.create(name="Object If Condition Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {
                    "id": str(customer.id),
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "age": customer.age,  
                }},
            type="TRIGGER",
        )
        
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="EXTRACT_FIELD",
            parameters={
                    "field_path": "data"
                },
            type="ACTION",
        )
        
        object_if_condition = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="OBJECT_IF_CONDITION",
            parameters={
                    "content_type_id": self.customer_content_type.id,
                    "field": self.customer_age_field.id,
                    "lookup": "equals",
                    "value": "99",
                },
            type="FLOW",
        )
        create_action = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="CREATE_OBJECT",
            parameters={
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "data": {
                        "first_name": "Jane",
                        "last_name": "Smith",
                        "age": 30,
                    }
                },
            type="ACTION",
        )
        
        workflow.connect_nodes(trigger, object_if_condition)
        
        # 3. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        # 4. Check that the branch stopped.
        self.assertEqual(
            workflow_run.execution_trace[-1]["route"]["port_id"],
            "false",
        )
    
    # ---------------------------------------
    # Flow: HUMAN_IN_THE_LOOP
    # ---------------------------------------
    def test_flow_object_human_in_the_loop_pauses_when_arrived(self):
        """
        UC: Users want human in the loop behavior
        
        Expected Result: Loop pauses until condition is met
        """
        workflow = Workflow.objects.create(
            name="Human approval workflow",
            enable_logging=True,
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_TRIGGER",
            parameters={"data": {"proposal": "ready"}},
            type="TRIGGER",
        )
        approval = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="HUMAN_IN_THE_LOOP",
            parameters={"message": "Create the payables?", "approvers": []},
            type="ACTION",
        )
        downstream = WorkflowNode.objects.create(
            workflow=workflow,
            sub_type="ENRICH_DATA",
            parameters={"data": {"approved": True}},
            type="ACTION",
        )
        workflow.connect_nodes(trigger, approval)
        workflow.connect_nodes(approval, downstream)

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            workflow_run = run_workflow(workflow, {"employee_id": 7})
            steps = list(workflow_run.steps.order_by("sequence"))

            self.assertEqual(
                [step.action_id for step in steps],
                ["HUMAN_TRIGGER", "HUMAN_IN_THE_LOOP"],
            )
            self.assertEqual(steps[-1].status, "PAUSED")
            self.assertEqual(workflow_run.execution_trace[-1]["status"], "paused")
            with steps[-1].output_file.open("r") as output_file:
                self.assertEqual(
                    json.load(output_file),
                    {"proposal": "ready", "employee_id": 7},
                )

            resumed_run = resume_workflow(steps[-1])

            steps[-1].refresh_from_db()
            self.assertEqual(steps[-1].status, "COMPLETED")
            self.assertEqual(
                [step.action_id for step in resumed_run.steps.order_by("sequence")],
                ["HUMAN_TRIGGER", "HUMAN_IN_THE_LOOP", "ENRICH_DATA"],
            )
            self.assertTrue(resumed_run.execution_trace[-1]["output"]["approved"])
    
    

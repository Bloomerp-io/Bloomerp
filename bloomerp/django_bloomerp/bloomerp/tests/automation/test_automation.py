from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.test import TransactionTestCase
from django_celery_beat.models import PeriodicTask
from regex import F

from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.automation.flows import object_if_condition
from bloomerp.automation.schema import WorkflowValueType
from bloomerp.automation.schema_resolver import resolve_node_output_schema
from bloomerp.automation.utils import enhanced_get_attr
from bloomerp.models import ApplicationField, User
from bloomerp.models.automation import Workflow, WorkflowEdge, WorkflowNode
from bloomerp.models.automation.workflow_run import WorkflowRun
from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.celery.tasks.workflow_task import run_scheduled_workflow
from bloomerp.services.workflow_services import (
    _serialize_trigger_data,
    format_execution_trace,
    run_workflow,
    run_workflow_async,
)
from bloomerp.signals.automations import setup_automation_signals
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
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe",
                        "age" : 20
                    }
                }
            },
            type=WorkflowNodeType.TRIGGER.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        
        self.end_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {
                    "content_type_id" : ContentType.objects.get_for_model(self.CustomerModel).id
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
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

        with patch("bloomerp.services.workflow_services.run_workflow_async.delay") as delay_mock:
            result = run_workflow(self.workflow, {"first_name": "John"})

        self.assertIsNone(result)
        delay_mock.assert_called_once_with(
            self.workflow.id,
            {"first_name": "John"},
        )

    def test_run_workflow_async_hydrates_model_instances_before_running_sync(self):
        workflow = Workflow.objects.create(
            name="Async employee workflow",
            run_asynchronously=True,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ON_OBJECT_CREATE",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.EmployeeModel).id,
                },
            },
            type=WorkflowNodeType.TRIGGER.value.id,
            created_by=self.user,
            updated_by=self.user,
        )

        with patch("bloomerp.services.workflow_services.run_workflow_async.delay"):
            employee = self.EmployeeModel.objects.create(
                first_name="Ava",
                last_name="Ng",
                email="ava@example.com",
                created_by=self.user,
                updated_by=self.user,
            )
        serialized_trigger_data = _serialize_trigger_data(
            {
                "event": "create",
                "sender": self.EmployeeModel,
                "instance": employee,
                "data": {"created": True},
            }
        )

        with patch("bloomerp.services.workflow_services.run_workflow_sync") as run_workflow_sync_mock:
            run_workflow_async(workflow.id, serialized_trigger_data)

        run_workflow_sync_mock.assert_called_once()
        called_workflow, called_trigger_data = run_workflow_sync_mock.call_args[0]
        self.assertEqual(called_workflow.id, workflow.id)
        self.assertIsInstance(called_trigger_data["instance"], self.EmployeeModel)
        self.assertEqual(called_trigger_data["instance"].id, employee.id)
        self.assertEqual(called_trigger_data["sender"], self.EmployeeModel)

    def test_run_workflow_async_returns_json_safe_result(self):
        with patch("bloomerp.services.workflow_services.run_workflow_sync") as run_workflow_sync_mock:
            workflow_run = WorkflowRun(id=123)
            run_workflow_sync_mock.return_value = workflow_run

            result = run_workflow_async(self.workflow.id, {"first_name": "John"})

        self.assertEqual(result, {"workflow_run_id": "123"})

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
            config={
                "sub_type": "SCHEDULE",
                "parameters": {
                    "schedule": "*/5 * * * *",
                    "timezone": "Europe/Brussels",
                },
            },
            type=WorkflowNodeType.TRIGGER.value.id,
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

        trigger.config["parameters"]["schedule"] = ""
        trigger.save(update_fields=["config"])
        self.assertFalse(
            PeriodicTask.objects.filter(name=f"bloomerp.workflow.schedule.{workflow.id}").exists()
        )

    def test_run_scheduled_workflow_returns_json_safe_result(self):
        workflow = Workflow.objects.create(
            name="Scheduled workflow result",
            created_by=self.user,
            updated_by=self.user,
        )

        with patch("bloomerp.services.workflow_services.run_workflow_sync") as run_workflow_sync_mock:
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
            config={
                "sub_type": "ON_OBJECT_CREATE",
                "parameters": {"content_type_id": content_type.id},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
            created_by=self.user,
            updated_by=self.user,
        )

        setup_automation_signals(refresh=True)

        with patch("bloomerp.signals.automations.run_workflow") as run_workflow_mock:
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
            config={
                "sub_type": "ON_OBJECT_DELETE",
                "parameters": {"content_type_id": content_type.id},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
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

        with patch("bloomerp.signals.automations.run_workflow") as run_workflow_mock:
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
            config={
                "sub_type": "ON_OBJECT_UPDATE",
                "parameters": {"content_type_id": content_type.id},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
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

        with patch("bloomerp.signals.automations.run_workflow") as run_workflow_mock:
            instance.age = 23
            instance.updated_by = self.user
            instance.save()

            run_workflow_mock.assert_called_once()

    # def test_object_create_workflow_can_send_email_to_created_employee(self):
    #     content_type = ContentType.objects.get_for_model(self.EmployeeModel)
    #     workflow = Workflow.objects.create(
    #         name="Employee welcome email",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     trigger = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "ON_OBJECT_CREATE",
    #             "parameters": {"content_type_id": content_type.id},
    #         },
    #         type=WorkflowNodeType.TRIGGER.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     email_action = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "SEND_EMAIL",
    #             "parameters": {
    #                 "recipient": "{{ input.instance.email }}",
    #                 "subject": "Welcome {{ input.instance.first_name }}",
    #                 "body": "Hi {{ input.instance.first_name }}, welcome to Bloomerp.",
    #             },
    #         },
    #         type=WorkflowNodeType.ACTION.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     WorkflowEdge.objects.create(
    #         from_node=trigger,
    #         to_node=email_action,
    #     )

    #     setup_automation_signals(refresh=True)

    #     with patch("bloomerp.automation.actions.send_email.send_email") as send_email_mock:
    #         self.EmployeeModel.objects.create(
    #             first_name="Ava",
    #             last_name="Ng",
    #             email="ava@example.com",
    #             created_by=self.user,
    #             updated_by=self.user,
    #         )

    #     send_email_mock.assert_called_once_with(
    #         "ava@example.com",
    #         "Welcome Ava",
    #         "Hi Ava, welcome to Bloomerp.",
    #     )
    
    def test_exeucte_node(self):
        """Tests the execution of a basic node"""
        data = self.start_node.execute({}) # Don't need to pass any data with human triggers
        
        self.assertEqual(self.start_node.config.get("parameters").get("data"), data)

    # def test_list_filter_summary_email_sends_one_email_with_active_employees(self):
    #     content_type = ContentType.objects.get_for_model(self.EmployeeModel)
    #     self.EmployeeModel.objects.create(
    #         first_name="Ava",
    #         last_name="Ng",
    #         email="ava@example.com",
    #         status="active",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     self.EmployeeModel.objects.create(
    #         first_name="Ben",
    #         last_name="Fox",
    #         email="ben@example.com",
    #         status="terminated",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )

    #     workflow = Workflow.objects.create(
    #         name="Active employee digest",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     trigger = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "HUMAN_TRIGGER",
    #             "parameters": {"data": {"run": True}},
    #         },
    #         type=WorkflowNodeType.TRIGGER.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     list_objects = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "LIST_OBJECTS",
    #             "parameters": {"content_type_id": content_type.id},
    #         },
    #         type=WorkflowNodeType.ACTION.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     filter_active = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "FILTER_OBJECTS",
    #             "parameters": {
    #                 "field": "status",
    #                 "operator": "exact",
    #                 "value": "active",
    #             },
    #         },
    #         type=WorkflowNodeType.FLOW.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     email_action = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "SEND_EMAIL",
    #             "parameters": {
    #                 "recipient": "hr@example.com",
    #                 "subject": "Active employees",
    #                 "body": "{{ input }}",
    #             },
    #         },
    #         type=WorkflowNodeType.ACTION.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     WorkflowEdge.objects.create(from_node=trigger, to_node=list_objects)
    #     WorkflowEdge.objects.create(from_node=list_objects, to_node=filter_active)
    #     WorkflowEdge.objects.create(from_node=filter_active, to_node=email_action)

    #     with patch("bloomerp.automation.actions.send_email.send_email") as send_email_mock:
    #         workflow_run = run_workflow(workflow, {})

    #     send_email_mock.assert_called_once()
    #     recipient, subject, body = send_email_mock.call_args.args
    #     self.assertEqual(recipient, "hr@example.com")
    #     self.assertEqual(subject, "Active employees")
    #     self.assertIn("ava@example.com", body)
    #     self.assertNotIn("ben@example.com", body)

    # def test_for_each_fans_filtered_employee_list_into_per_employee_emails(self):
    #     content_type = ContentType.objects.get_for_model(self.EmployeeModel)
    #     self.EmployeeModel.objects.create(
    #         first_name="Ava",
    #         last_name="Ng",
    #         email="ava@example.com",
    #         status="active",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     self.EmployeeModel.objects.create(
    #         first_name="Cy",
    #         last_name="Park",
    #         email="cy@example.com",
    #         status="active",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     self.EmployeeModel.objects.create(
    #         first_name="Ben",
    #         last_name="Fox",
    #         email="ben@example.com",
    #         status="terminated",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )

    #     workflow = Workflow.objects.create(
    #         name="Per employee email",
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     trigger = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "HUMAN_TRIGGER",
    #             "parameters": {"data": {"run": True}},
    #         },
    #         type=WorkflowNodeType.TRIGGER.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     list_objects = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "LIST_OBJECTS",
    #             "parameters": {"content_type_id": content_type.id},
    #         },
    #         type=WorkflowNodeType.ACTION.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     filter_active = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "FILTER_OBJECTS",
    #             "parameters": {
    #                 "field": "status",
    #                 "operator": "exact",
    #                 "value": "active",
    #             },
    #         },
    #         type=WorkflowNodeType.FLOW.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     for_each = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "FOR_EACH",
    #             "parameters": {},
    #         },
    #         type=WorkflowNodeType.FLOW.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     email_action = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "SEND_EMAIL",
    #             "parameters": {
    #                 "recipient": "{{ input.item.email }}",
    #                 "subject": "Hello {{ input.item.first_name }}",
    #                 "body": "Hi {{ input.item.first_name }}",
    #             },
    #         },
    #         type=WorkflowNodeType.ACTION.value.id,
    #         created_by=self.user,
    #         updated_by=self.user,
    #     )
    #     WorkflowEdge.objects.create(from_node=trigger, to_node=list_objects)
    #     WorkflowEdge.objects.create(from_node=list_objects, to_node=filter_active)
    #     WorkflowEdge.objects.create(from_node=filter_active, to_node=for_each)
    #     WorkflowEdge.objects.create(from_node=for_each, to_node=email_action)

    #     with patch("bloomerp.automation.actions.send_email.send_email") as send_email_mock:
    #         workflow_run = run_workflow(workflow, {})

    #     self.assertEqual(send_email_mock.call_count, 2)
    #     recipients = {call.args[0] for call in send_email_mock.call_args_list}
    #     self.assertEqual(recipients, {"ava@example.com", "cy@example.com"})
    #     self.assertNotIn("ben@example.com", recipients)
    #     fanout_entries = [
    #         entry
    #         for entry in workflow_run.execution_trace
    #         if entry["node_sub_type"] == "FOR_EACH"
    #     ]
    #     self.assertEqual(fanout_entries[0]["output"]["kind"], "fanout")
    #     self.assertEqual(fanout_entries[0]["output"]["item_count"], 2)
    
    # ---------------------------------------
    # Action: ENRICH
    # ---------------------------------------
    def test_action_enrich_adds_fields_to_input_object(self):
        workflow = Workflow.objects.create(
            name="Enrich Test Workflow",
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        enrich_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {
                    "data": {
                        "full_name": "John Doe"
                    }
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=enrich_action)

        workflow_run = run_workflow(workflow, {"first_name": "John", "last_name": "Doe"})

        enrich_output = workflow_run.execution_trace[1]["output"]
        self.assertEqual(enrich_output["full_name"], "John Doe")
        self.assertEqual(enrich_output["first_name"], "John")
        self.assertEqual(enrich_output["last_name"], "Doe")
        
    def test_action_enrich_with_overlapping_field_names(self):
        workflow = Workflow.objects.create(
            name="Enrich Overlapping Fields Test Workflow",
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        enrich_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {
                    "data": {
                        "first_name": "Jane",
                        "full_name": "Jane Doe"
                    }
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=enrich_action)

        workflow_run = run_workflow(workflow, {"first_name": "John", "last_name": "Doe"})

        enrich_output = workflow_run.execution_trace[1]["output"]
        print(enrich_output)
        self.assertEqual(enrich_output["first_name"], "Jane")
        self.assertEqual(enrich_output["full_name"], "Jane Doe")
        self.assertEqual(enrich_output["last_name"], "Doe")

    # ---------------------------------------
    # Action: EXTRACT_FIELD
    # ---------------------------------------
    def test_action_extract_field_extracts_field_from_input_object(self):
        """
        This test checks whether a field can be extracted from the input and returned as output
        """
        workflow = Workflow.objects.create(
            name="Extract Field Test Workflow",
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "user"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=extract_action)

        workflow_run = run_workflow(workflow, {"user": {"email": "john.doe@example.com"}})

        extract_output = workflow_run.execution_trace[1]["output"]
        self.assertEqual(extract_output, {"email": "john.doe@example.com"})

    def test_action_extract_field_with_path_not_refering_to_list_or_object(self):
        """
        Workflow nodes pass a typed value downstream. If the extracted field is
        primitive, the primitive itself is returned rather than being wrapped in
        an artificial object.
        """
        # 1. Create the workflow
        workflow = Workflow.objects.create(
            name="Extract Nested Field Test Workflow",
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "user"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=extract_action)

        # 2. Run the workflow with a primitive value at the specified field path
        workflow_run = run_workflow(workflow, {"user": "David"})

        
        extract_output = get_terminal_node_output(workflow_run)
        self.assertEqual(extract_output, "David")
    
    def test_action_extract_field_with_nested_field_path(self):
        """
        This test checks whether a field can be extracted from a nested field path in the input and returned as output
        """
        workflow = Workflow.objects.create(
            name="Extract Nested Field Test Workflow",
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "user.profile.email"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=extract_action)

        workflow_run = run_workflow(workflow, {"user": {"profile": {"email": "john.doe@example.com"}}})

        extract_output = get_terminal_node_output(workflow_run)
        self.assertEqual(extract_output, "john.doe@example.com")
    
    def test_action_extract_field_using_list_objects_action(self):
        """
        More E2E test of when to use this
        """
        # 1. Create the workflow
        workflow = Workflow.objects.create(
            name="Extract Field from list objects",
        )
        
        # 2. Create objects
        self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)
        self.CustomerModel.objects.create(first_name="Bob", last_name="Johnson", age=25)
        
        # 3. Create the nodes
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        list_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "queryset"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, list_action)
        workflow.connect_nodes(list_action, extract_action)
        
        # 5. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        # 6. Check the output of the extract action
        output = get_terminal_node_output(workflow_run)
        self.assertIsInstance(output, list)
        self.assertEqual(len(output), 2)
        self.assertEqual(enhanced_get_attr(output[0], "first_name"), "Alice")
        self.assertEqual(enhanced_get_attr(output[1], "first_name"), "Bob")
    
    def test_action_extract_field_maintains_output_format_in_downstream_nodes(self):
        # 1. Create the workflow
        workflow = Workflow.objects.create(
            name="Extract Field Output Format Test Workflow",
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {
                    "first_name": "John",
                    "last_name": "Doe",
                    "age": 20,
                    "interests": ["sports", "music"] 
                }},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "interests"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        workflow.connect_nodes(trigger, extract_action)
        
        # 2. Resolve output schema
        output_schema = resolve_node_output_schema(extract_action)
        self.assertEqual(output_schema.value_type, "list")
        self.assertEqual(output_schema.fields, [])

        workflow_run = run_workflow(workflow, {})
        self.assertEqual(get_terminal_node_output(workflow_run), ["sports", "music"])
    
    # ---------------------------------------
    # Action: LIST_OBJECTS
    # ---------------------------------------
    def test_action_list_objects_returns_objects_of_specified_content_type(self):
        # Create some test customers
        self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)
        self.CustomerModel.objects.create(first_name="Bob", last_name="Johnson", age=25)

        workflow = Workflow.objects.create(name="List Objects Test Workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {
                    "data" : {
                        "run": True
                    }    
                },
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        list_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=list_action)

        workflow_run = run_workflow(workflow, {})

        output = get_terminal_node_output(workflow_run)
        
        self.assertIn("queryset", output)
        self.assertIn("count", output)
        self.assertIn("content_type_id", output)
        self.assertEqual(output["count"], 2)
        
        obj_1 = output["queryset"][0]
        obj_2 = output["queryset"][1]
        self.assertEqual(enhanced_get_attr(obj_1, "first_name"), "Alice")
        self.assertEqual(enhanced_get_attr(obj_2, "first_name"), "Bob")
        self.assertEqual(output["content_type_id"], ContentType.objects.get_for_model(self.CustomerModel).id)
        self.assertEqual(output["count"], 2)
    
    # ----------------------------------------
    # Action: UPDATE_OBJECT
    # ----------------------------------------
    def test_action_update_object_updates_object_with_given_fields(self):
        FIRST_NAME = "Alice"
        LAST_NAME = "Smith"
        AGE = 30
        
        NEW_LAST_NAME = "Johnson"
        NEW_AGE = AGE + 1
        
        # 1. Create a test customer
        customer = self.CustomerModel.objects.create(first_name=FIRST_NAME, last_name=LAST_NAME, age=AGE)

        # 2. Create workflow
        workflow = Workflow.objects.create(name="Update Object Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node
        action = WorkflowNode.objects.create(
            workflow=workflow,
            type=WorkflowNodeType.ACTION.value.id,
            config={
                "sub_type" : "UPDATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "object_id": str(customer.id),
                    "fields": {
                        "age": "{{ input.age }}",
                        "last_name": "{{ input.last_name }}",
                    }
                }
            }
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 6. Run the workflow
        run_workflow(workflow, {"first_name" : FIRST_NAME, "last_name" : NEW_LAST_NAME, "age" : NEW_AGE})

        # 7. Refresh the customer from the database and check that it was updated
        customer.refresh_from_db()
        self.assertEqual(customer.age, NEW_AGE)
        self.assertEqual(customer.last_name, NEW_LAST_NAME)
        self.assertEqual(customer.first_name, FIRST_NAME)
    
        # 8. Check that the workflow execution trace contains the updated fields
        output_schema = resolve_node_output_schema(action)
        self.assertEqual(output_schema.value_type, WorkflowValueType.OBJECT.value)
        
        # 6. Check that the fields are there
        required_fields = ["instance", "status", "error_message"]
        for field in output_schema.fields:
            self.assertTrue(field.path in required_fields)
        
    def test_action_update_with_partial_fields_only(self):
        """
        UC: Sometimes updates only include partial fields
        Expected results: partial fields are updated, even if other required fields are not provided.
        """
        # 1. Create a test customer
        customer = self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)

        # 2. Create workflow
        workflow = Workflow.objects.create(name="Update Object Partial Fields Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node
        action = WorkflowNode.objects.create(
            workflow=workflow,
            type=WorkflowNodeType.ACTION.value.id,
            config={
                "sub_type" : "UPDATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "object_id": str(customer.id),
                    "fields": {
                        "age": "{{ input.age }}",
                    }
                }
            }
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 6. Run the workflow with only the age field provided
        run_workflow(workflow, {"age" : 35})

        # 7. Refresh the customer from the database and check that it was updated
        customer.refresh_from_db()
        self.assertEqual(customer.age, 35)
        self.assertEqual(customer.first_name, "Alice")
        self.assertEqual(customer.last_name, "Smith")
    
    # ----------------------------------------
    # Action: DELETE_OBJECT
    # ----------------------------------------
    def test_action_delete_object_deletes_object_with_given_content_type_and_id(self):
        #1. Create a test customer
        customer = self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)
        
        # 2. Create workflow
        workflow = Workflow.objects.create(name="Delete Object Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "DELETE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "object_id": str(customer.id),
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 6. Run the workflow
        run_workflow(workflow, {})
        
        # 7. Check that the customer was deleted
        self.assertFalse(self.CustomerModel.objects.filter(id=customer.id).exists())
        
        # 8. Check that the workflow execution trace contains the status of the delete action
        output_schema = resolve_node_output_schema(action)
        self.assertEqual(output_schema.value_type, WorkflowValueType.OBJECT.value)
        required_fields = ["status", "error_message", "deleted_object_id"]
        for field in output_schema.fields:
            self.assertTrue(field.path in required_fields)
    
    # ----------------------------------------
    # Action: CREATE_OBJECT
    # ----------------------------------------
    def test_action_create_object_creates_object_with_given_content_type_and_fields(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Create Object Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "fields": {
                        "first_name": "Alice",
                        "last_name": "Smith",
                        "age": 30
                    }
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow
        run_workflow(workflow, {})
        
        # 6. Check that the customer was created
        self.assertTrue(self.CustomerModel.objects.filter(first_name="Alice", last_name="Smith", age=30).exists())
        
    def test_action_create_object_with_resolved_fields_creates_object_with_given_content_type_and_fields(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Create Object with Resolved Fields Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with resolved fields
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "fields": {
                        "first_name": "{{ input.first_name }}",
                        "last_name": "{{ input.last_name }}",
                        "age": "{{ input.age }}"
                    }
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow with input data
        run_workflow(workflow, {"first_name": "Bob", "last_name": "Johnson", "age": 25})
        
        # 6. Check that the customer was created with the resolved fields
        self.assertTrue(self.CustomerModel.objects.filter(first_name="Bob", last_name="Johnson", age=25).exists())
    
    def test_action_create_object_with_foreign_key_passes_foreign_object_downstream(self):
        """
        This test checks whether creating an object with a foreign key reference actually passes down
        the object rather than the id
        """
        import uuid
        username = f"testuser_{uuid.uuid4().hex[:8]}"
        
        
        # 1. Create a user object
        user = get_user_model().objects.create_user(username=username, password="testpassword")
        
        # 2. Create workflow
        workflow = Workflow.objects.create(name="Create Object with Foreign Key Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node with a foreign key reference to the user
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "fields": {
                        "first_name": "Alice",
                        "last_name": "Smith",
                        "age": 30,
                        "created_by": user.id
                    }
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 5. Add extract action to extract the created object
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "instance.created_by.username"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        workflow.connect_nodes(action, extract_action)
        
        # 6. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        # 7. Check that the created object has the correct foreign key reference
        output = get_terminal_node_output(workflow_run)
        self.assertEqual(output, username)
        
        
    
    # ----------------------------------------
    # Action: SQL_QUERY
    # ----------------------------------------
    def test_action_sql_query_returns_list_of_objects_matching_query(self):
        # 1. Create some test customers
        self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)
        self.CustomerModel.objects.create(first_name="Bob", last_name="Johnson", age=25)

        # 2. Create workflow
        workflow = Workflow.objects.create(name="SQL Query Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node
        db_table = self.CustomerModel._meta.db_table
        query = f"SELECT * FROM {db_table} WHERE age > 26"
        
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "SQL_QUERY",
                "parameters": {
                    "query": query,
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 6. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertIn("result", output)
        self.assertIn("count", output)
        self.assertEqual(output["count"], 1)
        self.assertEqual(output["result"][0]["first_name"], "Alice")
        
    def test_action_sql_query_with_invalid_query_returns_error(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Invalid SQL Query Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with an invalid query
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "SQL_QUERY",
                "parameters": {
                    "query": f"SELECT non_existing_field FROM non_existing_table",
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertIn("error_message", output)
        self.assertIsNotNone(output["error_message"])
        
    # ----------------------------------------
    # Action: GET_OBJECT
    # ----------------------------------------
    def test_action_get_object_returns_object_with_given_content_type_and_id(self):
        # 1. Create a test customer
        customer = self.CustomerModel.objects.create(first_name="Alice", last_name="Smith", age=30)

        # 2. Create workflow
        workflow = Workflow.objects.create(name="Get Object Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "GET_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "object_id": str(customer.id),
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 6. Run the workflow
        workflow_run = run_workflow(workflow, {})

        output = get_terminal_node_output(workflow_run)
        
        self.assertIn("instance", output)
        self.assertEqual(enhanced_get_attr(output["instance"], "first_name"), "Alice")
        self.assertEqual(enhanced_get_attr(output["instance"], "last_name"), "Smith")
        self.assertEqual(enhanced_get_attr(output["instance"], "age"), 30)
    
    def test_action_get_object_returns_object_using_context(self):
        # 1. Create a test customer
        customer = self.CustomerModel.objects.create(first_name="Bob", last_name="Johnson", age=25)
        
        # 2. Create workflow
        workflow = Workflow.objects.create(name="Get Object with Context Test Workflow")
        
        # 3. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 4. Create the action node with object_id referring to the trigger context
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "GET_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "object_id": "{{ input.instance_id }}",
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 5. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 6. Run the workflow with the trigger context containing the customer id
        workflow_run = run_workflow(workflow, {"instance_id": str(customer.id)})
        
        output = get_terminal_node_output(workflow_run)
        self.assertIn("instance", output)
        self.assertEqual(enhanced_get_attr(output["instance"], "first_name"), "Bob")
        
    def test_action_get_object_with_invalid_id_returns_error(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Get Object with Invalid ID Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with an invalid object_id
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "GET_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "object_id": "9999",  # Assuming this ID does not exist
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertEqual(output["found"], False)
    
    # ----------------------------------------
    # Action: COMPUTE
    # ----------------------------------------
    def test_action_compute(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Compute Action Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with a simple computation
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "COMPUTE",
                "parameters": {
                    "expression": "{{ input.a }} + {{ input.b }}"
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow with input values for the computation
        workflow_run = run_workflow(workflow, {"a": 5, "b": 10})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertEqual(output["result"], 15)
    
    def test_action_compute_get_first_item_from_list(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Compute Action List Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with an expression that gets the first item from a list
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "COMPUTE",
                "parameters": {
                    "expression": "{{ input.numbers }}[2]"
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow with a list of numbers as input
        workflow_run = run_workflow(workflow, {"numbers": [10, 20, 30]})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertEqual(output["result"], 30)
    
    # ----------------------------------------
    # Action: CALL_API
    # ----------------------------------------
    def test_action_call_api(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Call API Action Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with API call configuration
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "CALL_API",
                "parameters": {
                    "method": "GET",
                    "endpoint": "https://jsonplaceholder.typicode.com/todos/1",
                    "headers": {},
                    "payload": None,
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertIn("status_code", output)
        self.assertIn("response", output)
        self.assertIn("status", output)
        self.assertEqual(output["status"], "success")
        self.assertEqual(output["status_code"], 200)
        self.assertEqual(output["response"]["id"], 1)
        
    def test_action_call_api_with_invalid_url_returns_error(self):
        # 1. Create workflow
        workflow = Workflow.objects.create(name="Call API with Invalid URL Test Workflow")
        
        # 2. Add trigger
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        # 3. Create the action node with an invalid URL
        action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type" : "CALL_API",
                "parameters": {
                    "method": "GET",
                    "endpoint": "https://invalid.url",
                    "headers": {},
                    "payload": None,
                }
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        # 4. Connect the nodes
        workflow.connect_nodes(trigger, action)
        
        # 5. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        output = get_terminal_node_output(workflow_run)
        
        self.assertIn("response", output)
        self.assertEqual(output["status"], "error")
    
    
    # ----------------------------------------
    # Flow: IF_CONDITION
    # ----------------------------------------
    def test_if_condition_continues_when_condition_matches(self):
        self.end_node.delete()
        if_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "IF_CONDITION",
                "parameters": {
                    "field": "age",
                    "operator": "exact",
                    "value": "20",
                },
            },
            type=WorkflowNodeType.FLOW.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=self.start_node, to_node=if_node)
        WorkflowEdge.objects.create(from_node=if_node, to_node=create_node)

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
            config={
                "sub_type": "IF_CONDITION",
                "parameters": {
                    "field": "age",
                    "operator": "exact",
                    "value": "99",
                },
            },
            type=WorkflowNodeType.FLOW.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        create_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=self.start_node, to_node=if_node)
        WorkflowEdge.objects.create(from_node=if_node, to_node=create_node)

        workflow_run = run_workflow(self.workflow, {})

        self.assertFalse(self.CustomerModel.objects.filter(first_name="John").exists())
        self.assertEqual(
            [entry["node_sub_type"] for entry in workflow_run.execution_trace],
            ["HUMAN_TRIGGER", "IF_CONDITION"],
        )
        self.assertEqual(
            workflow_run.execution_trace[-1]["output"]["kind"],
            "branch_stopped",
        )

    
    # ----------------------------------------
    # Flow: MERGE_BRANCHES
    # ----------------------------------------
    def test_merge_branches_waits_for_all_upstream_nodes_then_runs_downstream_once(self):
        workflow = Workflow.objects.create(name="Merge branches workflow")
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        left_branch = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {"data": {"left_value": "left"}},
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        right_branch = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {"data": {"right_value": "right"}},
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        merge_node = WorkflowNode.objects.create(
            workflow=workflow,
            config={"sub_type": "MERGE_BRANCHES", "parameters": {}},
            type=WorkflowNodeType.FLOW.value.id,
        )
        tail_node = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {
                    "data": {
                        "left": f"{{{{ input.node_{left_branch.id}.left_value }}}}",
                        "right": f"{{{{ input.node_{right_branch.id}.right_value }}}}",
                    }
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
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
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {
                    "data": {
                        "records": [
                            {"value": "A"},
                            {"value": "B"},
                        ]
                    }
                },
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        for_each_node = WorkflowNode.objects.create(
            workflow=workflow,
            config={"sub_type": "FOR_EACH", "parameters": {}},
            type=WorkflowNodeType.FLOW.value.id,
        )
        left_branch = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {"data": {"left_value": "{{ input.item.value }}-L"}},
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        right_branch = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {"data": {"right_value": "{{ input.item.value }}-R"}},
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        merge_node = WorkflowNode.objects.create(
            workflow=workflow,
            config={"sub_type": "MERGE_BRANCHES", "parameters": {}},
            type=WorkflowNodeType.FLOW.value.id,
        )
        tail_node = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ENRICH_DATA",
                "parameters": {
                    "data": {
                        "combined": (
                            f"{{{{ input.node_{left_branch.id}.left_value }}}}|"
                            f"{{{{ input.node_{right_branch.id}.right_value }}}}"
                        ),
                    }
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
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
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {
                    "data": {
                        "records": [
                            {"value": "A"},
                            {"value": "B"},
                        ]
                    }
                },
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        extract_records = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {"field_path": "records"},
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        for_each_node = WorkflowNode.objects.create(
            workflow=workflow,
            config={"sub_type": "FOR_EACH", "parameters": {}},
            type=WorkflowNodeType.FLOW.value.id,
        )
        merge_branch = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "MERGE_BRANCHES",
                "parameters": {},
            },
            type=WorkflowNodeType.FLOW.value.id,
        )
        send_message = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "SEND_USER_MESSAGE",
                "parameters": {
                    "user_id": str(self.user.id),
                    "message": (
                        f"{{{{ input.node_{trigger.id}.records.0.value }}}}|"
                        f"{{{{ input.node_{for_each_node.id}.item.value }}}}"
                    ),
                    "message_type": "success",
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )

        workflow.connect_nodes(trigger, extract_records)
        workflow.connect_nodes(extract_records, for_each_node)
        workflow.connect_nodes(for_each_node, merge_branch)
        workflow.connect_nodes(trigger, merge_branch)
        workflow.connect_nodes(merge_branch, send_message)

        with patch("bloomerp.automation.actions.send_user_message.send_user_message") as send_message_mock:
            workflow_run = run_workflow(workflow, {})

        self.assertEqual(send_message_mock.call_count, 2)
        messages = [
            call.kwargs["payload"]["message"]
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
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {
                    "id": str(customer.id),
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "age": customer.age,  
                }},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "data"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        object_if_condition = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "OBJECT_IF_CONDITION",
                "parameters": {
                    "content_type_id": self.customer_content_type.id,
                    "field": self.customer_age_field.id,
                    "lookup": "equals",
                    "value": "20",
                },
            },
            type=WorkflowNodeType.FLOW.value.id,
        )
        create_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "data": {
                        "first_name": "Jane",
                        "last_name": "Smith",
                        "age": 30,
                    }
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
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
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {
                    "id": str(customer.id),
                    "first_name": customer.first_name,
                    "last_name": customer.last_name,
                    "age": customer.age,  
                }},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
        )
        
        extract_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "EXTRACT_FIELD",
                "parameters": {
                    "field_path": "data"
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        object_if_condition = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "OBJECT_IF_CONDITION",
                "parameters": {
                    "content_type_id": self.customer_content_type.id,
                    "field": self.customer_age_field.id,
                    "lookup": "equals",
                    "value": "99",
                },
            },
            type=WorkflowNodeType.FLOW.value.id,
        )
        create_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {
                    "content_type_id": ContentType.objects.get_for_model(self.CustomerModel).id,
                    "data": {
                        "first_name": "Jane",
                        "last_name": "Smith",
                        "age": 30,
                    }
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
        )
        
        workflow.connect_nodes(trigger, object_if_condition)
        
        # 3. Run the workflow
        workflow_run = run_workflow(workflow, {})
        
        # 4. Check that the branch stopped.
        self.assertEqual(
            workflow_run.execution_trace[-1]["output"]["kind"],
            "branch_stopped",
        )
    
    # ---------------------------------------
    # Tests for document template generation
    # ---------------------------------------
    # def test_action_create_document_template(self):
    #     # 1. Create a document template
    #     document_template = DocumentTemplate.objects.create(
    #         name="Test",
    #         template="""
    #         <div>Hello World</div>
    #         """
    #     )
        
    #     # 2. Create workflow
    #     workflow = Workflow.objects.create(name="Document template generator")
        
    #     # 3. Add trigger
    #     trigger = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "HUMAN_TRIGGER",
    #             "parameters": {"data": {"run": True}},
    #         },
    #         type=WorkflowNodeType.TRIGGER.value.id,
    #     )
        
    #     # 4. Create the action node
    #     action = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         type=WorkflowNodeType.ACTION.value.id,
    #         config={
    #             "sub_type" : "GENERATE_PDF"
    #         }
    #     )
        
    #     # 5. Connect the nodes
    #     workflow.connect_nodes(trigger, action)
        
    #     # 6. Run the workflow
    #     result = run_workflow(workflow, {})
    #     self.assertIn("pdf_url", result)
        
        
    # def test_action_create_document_template_with_input(self):
    #     # 1. Create a document template
    #     document_template = DocumentTemplate.objects.create(
    #         name="Test with input",
    #         template="""
    #         <div>Hello {{ input.name }}</div>
    #         """
    #     )
        
    #     # 2. Create workflow
    #     workflow = Workflow.objects.create(name="Document template generator with input")
        
    #     # 3. Add trigger
    #     trigger = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         config={
    #             "sub_type": "HUMAN_TRIGGER",
    #             "parameters": {"data": {"name": "Alice"}},
    #         },
    #         type=WorkflowNodeType.TRIGGER.value.id,
    #     )
        
    #     # 4. Create the action node
    #     action = WorkflowNode.objects.create(
    #         workflow=workflow,
    #         type=WorkflowNodeType.ACTION.value.id,
    #         config={
    #             "sub_type" : "GENERATE_PDF"
    #         }
    #     )
        
    #     # 5. Connect the nodes
    #     workflow.connect_nodes(trigger, action)
        
    #     # 6. Run the workflow
    #     result = run_workflow(workflow, {})
    #     self.assertIn("pdf_url", result)
        
    
    

from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.test import TransactionTestCase

from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.models import User
from bloomerp.models.automation import Workflow, WorkflowEdge, WorkflowNode
from bloomerp.services.workflow_services import format_execution_trace, run_workflow
from bloomerp.signals.automations import setup_automation_signals
from bloomerp.tests.utils.dynamic_models import create_test_models

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

    def test_object_create_workflow_can_send_email_to_created_employee(self):
        content_type = ContentType.objects.get_for_model(self.EmployeeModel)
        workflow = Workflow.objects.create(
            name="Employee welcome email",
            created_by=self.user,
            updated_by=self.user,
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "ON_OBJECT_CREATE",
                "parameters": {"content_type_id": content_type.id},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        email_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "SEND_EMAIL",
                "parameters": {
                    "recipient": "{{ input.instance.email }}",
                    "subject": "Welcome {{ input.instance.first_name }}",
                    "body": "Hi {{ input.instance.first_name }}, welcome to Bloomerp.",
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(
            from_node=trigger,
            to_node=email_action,
        )

        setup_automation_signals(refresh=True)

        with patch("bloomerp.automation.actions.send_email.send_email") as send_email_mock:
            self.EmployeeModel.objects.create(
                first_name="Ava",
                last_name="Ng",
                email="ava@example.com",
                created_by=self.user,
                updated_by=self.user,
            )

        send_email_mock.assert_called_once_with(
            "ava@example.com",
            "Welcome Ava",
            "Hi Ava, welcome to Bloomerp.",
        )
    
    
    def test_exeucte_node(self):
        """Tests the execution of a basic node"""
        data = self.start_node.execute({}) # Don't need to pass any data with human triggers
        
        self.assertEqual(self.start_node.config.get("parameters").get("data"), data)

    def test_list_filter_summary_email_sends_one_email_with_active_employees(self):
        content_type = ContentType.objects.get_for_model(self.EmployeeModel)
        self.EmployeeModel.objects.create(
            first_name="Ava",
            last_name="Ng",
            email="ava@example.com",
            status="active",
            created_by=self.user,
            updated_by=self.user,
        )
        self.EmployeeModel.objects.create(
            first_name="Ben",
            last_name="Fox",
            email="ben@example.com",
            status="terminated",
            created_by=self.user,
            updated_by=self.user,
        )

        workflow = Workflow.objects.create(
            name="Active employee digest",
            created_by=self.user,
            updated_by=self.user,
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        list_objects = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {"content_type_id": content_type.id},
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        filter_active = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "FILTER_OBJECTS",
                "parameters": {
                    "field": "status",
                    "operator": "exact",
                    "value": "active",
                },
            },
            type=WorkflowNodeType.FLOW.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        email_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "SEND_EMAIL",
                "parameters": {
                    "recipient": "hr@example.com",
                    "subject": "Active employees",
                    "body": "{{ input }}",
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=list_objects)
        WorkflowEdge.objects.create(from_node=list_objects, to_node=filter_active)
        WorkflowEdge.objects.create(from_node=filter_active, to_node=email_action)

        with patch("bloomerp.automation.actions.send_email.send_email") as send_email_mock:
            workflow_run = run_workflow(workflow, {})

        send_email_mock.assert_called_once()
        recipient, subject, body = send_email_mock.call_args.args
        self.assertEqual(recipient, "hr@example.com")
        self.assertEqual(subject, "Active employees")
        self.assertIn("ava@example.com", body)
        self.assertNotIn("ben@example.com", body)

    def test_for_each_fans_filtered_employee_list_into_per_employee_emails(self):
        content_type = ContentType.objects.get_for_model(self.EmployeeModel)
        self.EmployeeModel.objects.create(
            first_name="Ava",
            last_name="Ng",
            email="ava@example.com",
            status="active",
            created_by=self.user,
            updated_by=self.user,
        )
        self.EmployeeModel.objects.create(
            first_name="Cy",
            last_name="Park",
            email="cy@example.com",
            status="active",
            created_by=self.user,
            updated_by=self.user,
        )
        self.EmployeeModel.objects.create(
            first_name="Ben",
            last_name="Fox",
            email="ben@example.com",
            status="terminated",
            created_by=self.user,
            updated_by=self.user,
        )

        workflow = Workflow.objects.create(
            name="Per employee email",
            created_by=self.user,
            updated_by=self.user,
        )
        trigger = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"run": True}},
            },
            type=WorkflowNodeType.TRIGGER.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        list_objects = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {"content_type_id": content_type.id},
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        filter_active = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "FILTER_OBJECTS",
                "parameters": {
                    "field": "status",
                    "operator": "exact",
                    "value": "active",
                },
            },
            type=WorkflowNodeType.FLOW.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        for_each = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "FOR_EACH",
                "parameters": {},
            },
            type=WorkflowNodeType.FLOW.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        email_action = WorkflowNode.objects.create(
            workflow=workflow,
            config={
                "sub_type": "SEND_EMAIL",
                "parameters": {
                    "recipient": "{{ input.item.email }}",
                    "subject": "Hello {{ input.item.first_name }}",
                    "body": "Hi {{ input.item.first_name }}",
                },
            },
            type=WorkflowNodeType.ACTION.value.id,
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=trigger, to_node=list_objects)
        WorkflowEdge.objects.create(from_node=list_objects, to_node=filter_active)
        WorkflowEdge.objects.create(from_node=filter_active, to_node=for_each)
        WorkflowEdge.objects.create(from_node=for_each, to_node=email_action)

        with patch("bloomerp.automation.actions.send_email.send_email") as send_email_mock:
            workflow_run = run_workflow(workflow, {})

        self.assertEqual(send_email_mock.call_count, 2)
        recipients = {call.args[0] for call in send_email_mock.call_args_list}
        self.assertEqual(recipients, {"ava@example.com", "cy@example.com"})
        self.assertNotIn("ben@example.com", recipients)
        fanout_entries = [
            entry
            for entry in workflow_run.execution_trace
            if entry["node_sub_type"] == "FOR_EACH"
        ]
        self.assertEqual(fanout_entries[0]["output"]["kind"], "fanout")
        self.assertEqual(fanout_entries[0]["output"]["item_count"], 2)
    
    
    

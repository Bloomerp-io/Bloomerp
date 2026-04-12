from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.test import TransactionTestCase

from bloomerp.automation.defintion import WorkflowNodeType
from bloomerp.models import User
from bloomerp.models.automation import Workflow, WorkflowEdge, WorkflowNode
from bloomerp.services.workflow_services import run_workflow
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
        run_workflow(self.workflow, data)
    
        # 3. Check the result
        qs = self.CustomerModel.objects.filter(
            first_name="John",
            last_name="Doe"
        )
        self.assertTrue(qs.exists())
    
    
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
    
    
    def test_exeucte_node(self):
        """Tests the execution of a basic node"""
        data = self.start_node.execute({}) # Don't need to pass any data with human triggers
        
        self.assertEqual(self.start_node.config.get("parameters").get("data"), data)
    
    
    
from bloomerp.services.workflow_services import run_workflow
from bloomerp.models.automation import Workflow, WorkflowNode, WorkflowEdge
from bloomerp.automation.defintion import WorkflowNodeType
from django.test import TransactionTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from django.db import models

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
        self.workflow = Workflow.objects.create(name="Test Workflow")
        
        start_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            node_type="start",
            config={
                    "sub_type" : "HUMMAN_TRIGGER",
                    "parameters" : {
                        "data" : {
                            "first_name" : "John",
                            "last_name" : "Doe"
                        }
                    }
                },
            type=WorkflowNodeType.TRIGGER.value.name
        )
        
        end_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            node_type="end",
            config={
                    "sub_type" : "CREATE_RECORD",
                    "parameters" : {}
                },
            type=WorkflowNodeType.ACTION.value.name
        )
        
        WorkflowEdge.objects.create(
            from_node=start_node,
            to_node=end_node,
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
    
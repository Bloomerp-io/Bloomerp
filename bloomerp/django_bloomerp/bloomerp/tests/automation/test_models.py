from django.test import TestCase
from bloomerp.models import Workflow, WorkflowEdge, WorkflowNode, User
from bloomerp.automation.defintion import WorkflowNodeType
from django.core.exceptions import ValidationError

from bloomerp.models.automation import workflow  # Import ValidationError

class TestAutomationModels(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="password")

        self.workflow = Workflow.objects.create(
            name="Test Workflow"
        )

        self.start_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {
                    "data": {
                        "first_name": "John",
                        "last_name": "Doe"
                    }
                }
            },
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user
        )

        self.end_node = WorkflowNode.objects.create(
            created_by=self.user,
            updated_by=self.user,
            workflow=self.workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {}
            },
            type="ACTION",
        )
        
        self.other_node = WorkflowNode.objects.create(
            created_by=self.user,
            updated_by=self.user,
            workflow=self.workflow,
            config={
                "sub_type" : "CREATE_OBJECT",
                "parameters" : {}
            },
            type="ACTION",
        )

        self.yet_another_node = WorkflowNode.objects.create(
            created_by=self.user,
            updated_by=self.user,
            workflow=self.workflow,
            config={
                "sub_type" : "SEND_EMAIL",
                "parameters" : {}
            },
            type="ACTION",
        )
    
        WorkflowEdge.objects.create(
            from_node=self.start_node,
            to_node=self.end_node,
        )
        
        WorkflowEdge.objects.create(
            from_node=self.start_node,
            to_node=self.other_node
        )
        
        WorkflowEdge.objects.create(
            from_node=self.other_node,
            to_node=self.yet_another_node
        )
        
        return super().setUp()
    
    
    def test_get_trigger(self):
        """
        Tests whether the trigger retrieving functionality for a model works.
        """
        self.assertEqual(self.workflow.get_trigger(), self.start_node)
        
    
    def test_multiple_triggers_not_allowed(self):
        """
        Tests whether it is allowed to have multiple triggers.
        Expected: ValidationError is raised.
        """
        with self.assertRaises(ValidationError):
            WorkflowNode.objects.create(
                workflow=self.workflow,
                config={
                    "sub_type": "HUMAN_TRIGGER",
                    "parameters": {}
                },
                type="TRIGGER",
                created_by=self.user,
                updated_by=self.user
            )
    
    
    def test_get_triggers_by_subtype(self):
        """
        Tests whether the `get_triggers_by_type` method correctly filters WorkflowNode objects by trigger subtype.
        """
        trigger_nodes = WorkflowNode.get_triggers_by_type("HUMAN_TRIGGER")
        self.assertIn(self.start_node, trigger_nodes)
        self.assertNotIn(self.end_node, trigger_nodes)

    
    def test_get_output_nodes(self):
        """
        Checks if the get output nodes works well
        """
        trigger = self.workflow.get_trigger()
        output_nodes = trigger.get_output_nodes()
        
        self.assertIn(self.end_node, output_nodes)
        self.assertIn(self.other_node, output_nodes)
        self.assertNotIn(self.yet_another_node, output_nodes)
    
    
    def test_get_node_subtype(self):
        """
        Tests whether the retrieval of a NodeSubType defintion works 
        by retrieval of the ID
        """
        self.assertEqual(self.start_node.node_sub_type.name, "Human Trigger")
    
    
    def test_raises_validation_error_for_non_existing_node_subtype(self):
        """This test checks whether an error is raised if a node subtype does not exist"""
        with self.assertRaises(ValidationError):
            WorkflowNode.objects.create(
                created_by=self.user,
                updated_by=self.user,
                type="ACTION",
                config={
                    "sub_type" : "DOES_NOT_EXIST",
                    "parameters" : {}
                }
            )
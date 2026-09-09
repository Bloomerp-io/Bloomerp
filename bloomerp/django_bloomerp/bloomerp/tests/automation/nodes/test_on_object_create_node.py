


from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.tests.base.workflow_node_test_case import BloomerpWorkflowNodeTestCase, WorkflowNodeSimulation

class TestOnObjectCreateNode(BloomerpWorkflowNodeTestCase):
    node_id = "ON_OBJECT_CREATE"
    
    def get_simulations(self):
        return [
            WorkflowNodeSimulation(
                
            )
        ]
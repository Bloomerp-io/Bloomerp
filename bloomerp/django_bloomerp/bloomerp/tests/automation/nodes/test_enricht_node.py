


from bloomerp.models.automation.workflow_node import WorkflowNode
from bloomerp.tests.base.workflow_node_test_case import BloomerpWorkflowNodeTestCase, WorkflowNodeScenario

class TestEnrichNode(BloomerpWorkflowNodeTestCase):
    node_id = "ENRICH_DATA"
    
    def get_simulations(self):
        return [
            WorkflowNodeScenario(
                name="Normal enrichment",
                trigger_data={
                    "start" : "start"    
                },
                nodes=[
                    self.add_node(
                        self.node_id,
                        parameters={
                            "data": {"additional": 123}
                        }
                    )
                ],
                expected_output={
                    "start" : "start",
                    "additional" : 123
                }
            ),
            WorkflowNodeScenario(
                name="Enrichment with no dictionary",
                
            )
        ]

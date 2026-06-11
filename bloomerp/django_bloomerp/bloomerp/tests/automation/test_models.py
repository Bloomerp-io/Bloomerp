import json

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.urls import reverse
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

    def test_update_workflow_keeps_new_nodes_and_response_client_ids(self):
        self.client.force_login(self.user)

        payload = {
            "workflow_id": self.workflow.id,
            "name": "Updated Workflow",
            "nodes": [
                {
                    "id": self.start_node.id,
                    "client_id": "node-1",
                    "type": "TRIGGER",
                    "config": {
                        "sub_type": "HUMAN_TRIGGER",
                        "parameters": {"data": {"d": "d"}},
                    },
                    "pos_x": 129,
                    "pos_y": 192,
                },
                {
                    "id": self.end_node.id,
                    "client_id": "node-2",
                    "type": "ACTION",
                    "config": {
                        "sub_type": "SEND_EMAIL",
                        "parameters": {
                            "recipient": "David",
                            "subject": "Dubrik",
                            "body": "You",
                        },
                    },
                    "pos_x": 596,
                    "pos_y": 293,
                },
                {
                    "client_id": "node-3",
                    "type": "ACTION",
                    "config": {
                        "sub_type": "SEND_EMAIL",
                        "parameters": {
                            "recipient": "David",
                            "subject": "Second",
                            "body": "Still here",
                        },
                    },
                    "pos_x": 596,
                    "pos_y": 100,
                },
            ],
            "edges": [
                {"from_node": "node-1", "to_node": "node-2"},
                {"from_node": "node-1", "to_node": "node-3"},
            ],
        }

        response = self.client.post(
            reverse("components_automation_save_workflow"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(len(response_data["nodes"]), 3)
        self.assertEqual(len(response_data["edges"]), 2)
        self.assertEqual(
            {node["client_id"] for node in response_data["nodes"]},
            {"node-1", "node-2", "node-3"},
        )
        self.assertEqual(
            {
                (edge["from_node"], edge["to_node"])
                for edge in response_data["edges"]
            },
            {("node-1", "node-2"), ("node-1", "node-3")},
        )
        self.assertEqual(self.workflow.nodes.count(), 3)

    def test_update_workflow_defaults_invalid_node_positions(self):
        self.client.force_login(self.user)

        payload = {
            "workflow_id": self.workflow.id,
            "name": "Updated Workflow",
            "nodes": [
                {
                    "id": self.start_node.id,
                    "client_id": "node-1",
                    "type": "TRIGGER",
                    "config": {
                        "sub_type": "HUMAN_TRIGGER",
                        "parameters": {"data": {"d": "d"}},
                    },
                    "pos_x": None,
                    "pos_y": "",
                },
                {
                    "id": self.end_node.id,
                    "client_id": "node-2",
                    "type": "ACTION",
                    "config": {
                        "sub_type": "SEND_EMAIL",
                        "parameters": {
                            "recipient": "David",
                            "subject": "Dubrik",
                            "body": "You",
                        },
                    },
                    "pos_x": "not-ready",
                },
            ],
            "edges": [{"from_node": "node-1", "to_node": "node-2"}],
        }

        response = self.client.post(
            reverse("components_automation_save_workflow"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        node_by_client_id = {
            node["client_id"]: node for node in response_data["nodes"]
        }
        self.assertEqual(node_by_client_id["node-1"]["pos_x"], 0)
        self.assertEqual(node_by_client_id["node-1"]["pos_y"], 0)
        self.assertEqual(node_by_client_id["node-2"]["pos_x"], 0)
        self.assertEqual(node_by_client_id["node-2"]["pos_y"], 0)

    def test_update_workflow_uses_db_shaped_client_ids_when_ids_are_missing(self):
        self.client.force_login(self.user)
        payload = {
            "workflow_id": self.workflow.id,
            "name": "Workflow",
            "nodes": [
                {
                    "client_id": f"node-{self.start_node.id}",
                    "type": "TRIGGER",
                    "config": {
                        "sub_type": "HUMAN_TRIGGER",
                        "parameters": {"data": {"d": "d"}},
                    },
                    "pos_x": 129,
                    "pos_y": 192,
                },
                {
                    "client_id": f"node-{self.end_node.id}",
                    "type": "FLOW",
                    "config": {
                        "sub_type": "FILTER_OBJECTS",
                        "parameters": {
                            "field": "status",
                            "operator": "exact",
                            "value": "active",
                        },
                    },
                    "pos_x": 500,
                    "pos_y": 192,
                },
                {
                    "client_id": "node-new-for-each",
                    "type": "FLOW",
                    "config": {"sub_type": "FOR_EACH", "parameters": {}},
                    "pos_x": 774,
                    "pos_y": 192,
                },
            ],
            "edges": [
                {
                    "from_node": f"node-{self.start_node.id}",
                    "to_node": f"node-{self.end_node.id}",
                },
                {
                    "from_node": f"node-{self.end_node.id}",
                    "to_node": "node-new-for-each",
                },
            ],
        }

        response = self.client.post(
            reverse("components_automation_save_workflow"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            WorkflowNode.objects.filter(
                workflow=self.workflow,
                type="TRIGGER",
            ).count(),
            1,
        )
        response_data = response.json()
        self.assertEqual(len(response_data["nodes"]), 3)
        self.assertIn(
            f"node-{self.start_node.id}",
            {node["client_id"] for node in response_data["nodes"]},
        )

    def test_render_workflow_node_uses_dedicated_template(self):
        self.client.force_login(self.user)
        if_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "IF_CONDITION",
                "parameters": {
                    "field": "status",
                    "operator": "exact",
                    "value": "active",
                },
            },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse("components_automation_render_workflow_node"),
            {
                "node_id": if_node.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('data-workflow-node-config-form="true"', content)
        self.assertIn("If Condition", content)
        self.assertIn("workflow-node-config-fields", content)
    def test_render_workflow_node_can_edit_config_as_json(self):
        self.client.force_login(self.user)
        if_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "IF_CONDITION",
                "parameters": {
                    "field": "status",
                    "operator": "exact",
                    "value": "{{ input.status }}",
                },
            },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse("components_automation_render_workflow_node"),
            {
                "node_id": if_node.id,
                "edit_mode": "json",
            },
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('data-edit-mode="json"', content)
        self.assertIn('name="parameters"', content)
        self.assertIn("Config JSON", content)
        self.assertIn("{{ input.status }}", content)

    def test_render_workflow_node_schema_panel_returns_output_values(self):
        self.client.force_login(self.user)
        content_type = ContentType.objects.get_for_model(User)
        list_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {"content_type_id": content_type.id},
            },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse("components_automation_render_workflow_node_schema_panel"),
            {"node_id": list_node.id},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('data-workflow-node-schema-panel', content)
        self.assertIn("Values this node passes to next nodes", content)
        self.assertIn("Username", content)

    def test_model_backed_schema_panel_includes_output_paths(self):
        self.client.force_login(self.user)
        content_type = ContentType.objects.get_for_model(User)
        list_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {"content_type_id": content_type.id},
            },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse("components_automation_render_workflow_node_schema_panel"),
            {"node_id": list_node.id},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Values this node passes to next nodes", content)
        self.assertIn("input.0.username", content)

    def test_schema_panel_resolves_upstream_schema_recursively(self):
        self.client.force_login(self.user)
        content_type = ContentType.objects.get_for_model(User)
        list_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "LIST_OBJECTS",
                "parameters": {"content_type_id": content_type.id},
            },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        filter_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "FILTER_OBJECTS",
                "parameters": {
                    "field": "is_active",
                    "operator": "truthy",
                    "value": "",
                },
            },
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        for_each_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={"sub_type": "FOR_EACH", "parameters": {}},
            type="FLOW",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(from_node=list_node, to_node=filter_node)
        WorkflowEdge.objects.create(from_node=filter_node, to_node=for_each_node)

        response = self.client.get(
            reverse("components_automation_render_workflow_node_schema_panel"),
            {"node_id": for_each_node.id},
        )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Values you can use in this node", content)
        self.assertIn("Values this node passes to next nodes", content)
        self.assertIn("input.0.username", content)
        self.assertIn("input.item.username", content)
    
    
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


class TestWorkflowSaveDraftClientIds(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="draft-client-user", password="password")
        self.workflow = Workflow.objects.create(name="Draft Client Workflow")
        self.start_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "HUMAN_TRIGGER",
                "parameters": {"data": {"d": "d"}},
            },
            type="TRIGGER",
            created_by=self.user,
            updated_by=self.user,
        )
        self.action_node = WorkflowNode.objects.create(
            workflow=self.workflow,
            config={
                "sub_type": "CREATE_OBJECT",
                "parameters": {},
            },
            type="ACTION",
            created_by=self.user,
            updated_by=self.user,
        )
        WorkflowEdge.objects.create(
            from_node=self.start_node,
            to_node=self.action_node,
        )
        return super().setUp()

    def test_update_workflow_accepts_draft_client_ids_for_new_nodes(self):
        self.client.force_login(self.user)
        payload = {
            "workflow_id": self.workflow.id,
            "name": "Workflow",
            "nodes": [
                {
                    "id": self.start_node.id,
                    "client_id": "node-1",
                    "type": "TRIGGER",
                    "config": {
                        "sub_type": "HUMAN_TRIGGER",
                        "parameters": {"data": {"d": "d"}},
                    },
                    "pos_x": 129,
                    "pos_y": 192,
                },
                {
                    "id": self.action_node.id,
                    "client_id": "node-2",
                    "type": "ACTION",
                    "config": {
                        "sub_type": "CREATE_OBJECT",
                        "parameters": {},
                    },
                    "pos_x": 500,
                    "pos_y": 192,
                },
                {
                    "client_id": "draft-7",
                    "type": "FLOW",
                    "config": {"sub_type": "FOR_EACH", "parameters": {}},
                    "pos_x": 774,
                    "pos_y": 192,
                },
            ],
            "edges": [
                {
                    "from_node": "node-1",
                    "to_node": "node-2",
                },
                {
                    "from_node": "node-2",
                    "to_node": "draft-7",
                },
            ],
        }

        response = self.client.post(
            reverse("components_automation_save_workflow"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn(
            "draft-7",
            {node["client_id"] for node in response_data["nodes"]},
        )
        self.assertIn(
            ("node-2", "draft-7"),
            {
                (edge["from_node"], edge["to_node"])
                for edge in response_data["edges"]
            },
        )
        self.assertEqual(self.workflow.nodes.count(), 3)

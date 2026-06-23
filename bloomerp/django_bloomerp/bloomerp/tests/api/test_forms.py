

from bloomerp.models.forms.form import Form
from bloomerp.tests.base import BaseBloomerpModelTestCase
from django.contrib.contenttypes.models import ContentType
import json
import requests

class TestFormAPI(BaseBloomerpModelTestCase):
    
    def create_form(self, **kwargs):
        """
        Helper function to create a form with default values for testing
        """
        defaults = {
            "name": "Test Form",
            "description": "A form for testing",
            "requires_review": False,
            "requires_authentication": False,
            "public_embed_enabled": False,
            "max_submissions": None,
            "max_submissions_per_ip": None,
            "opens_at": None,
            "closes_at": None,
            "content_type": ContentType.objects.get_for_model(self.CustomerModel)
        }
        defaults.update(kwargs)
        form = Form.objects.create(**defaults)
        return form
    
    def test_form_with_public_embed_enabled_has_endpoint(self):
        """
        Tests whether form with 'public_embed_enabled' has an endpoint
        through which a form can be submitted
        """
        # 1. Create a form
        form = self.create_form(public_embed_enabled=True)
        
        # 2. Get the form's public endpoint URL
        endpoint = form.submit_api_url
        
        # 3. Assert that the endpoint is correct
        expected_endpoint = f"/api/forms/{form.id}/submit/"
        self.assertEqual(endpoint, expected_endpoint)
        
        # 4. Assert that the endpoint is accessible (returns 200)
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 200)
        
    
    def test_form_with_public_embed_disabled_does_not_have_endpoint(self):
        """
        Tests whether form with 'public_embed_enabled' set to False does not have an endpoint
        through which a form can be submitted
        """
        # 1. Create a form with public_embed_enabled set to False
        form = self.create_form(public_embed_enabled=False)
        
        # 2. Get the form's public endpoint URL
        endpoint = form.submit_api_url
        
        # 3. Assert that the endpoint is correct
        expected_endpoint = f"/api/forms/{form.id}/submit/"
        self.assertEqual(endpoint, expected_endpoint)
        
        # 4. Assert that the endpoint is not accessible (returns 404)
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 404)
        
    def test_form_with_public_endpoint_but_required_authentication_is_not_accessible(self):
        """
        Tests whether form with 'public_embed_enabled' set to True but 'requires_authentication' set to True is not accessible
        through the public endpoint
        """
        # 1. Create a form with public_embed_enabled set to True and requires_authentication set to True
        form = self.create_form(public_embed_enabled=True, requires_authentication=True)
        
        # 2. Get the form's public endpoint URL
        endpoint = form.submit_api_url
        
        # 3. Assert that the endpoint is correct
        expected_endpoint = f"/api/forms/{form.id}/submit/"
        self.assertEqual(endpoint, expected_endpoint)
        
        # 4. Assert that the endpoint is not accessible (returns 403)
        response = self.client.get(endpoint)
        self.assertEqual(response.status_code, 403)
        
        
    def test_form_submission_through_public_endpoint(self):
        """
        Tests whether a form can be submitted through the public endpoint when 'public_embed_enabled' is set to True
        """
        # 1. Create a form with public_embed_enabled set to True
        form = self.create_form(public_embed_enabled=True)
        
        # 2. Get the form's public endpoint URL
        endpoint = form.submit_api_url
        
        # 3. Assert that the endpoint is correct
        expected_endpoint = f"/api/forms/{form.id}/submit/"
        self.assertEqual(endpoint, expected_endpoint)
        
        # 4. Submit data to the endpoint and assert that it returns 200
        response = self.client.post(endpoint, data={"first_name": "John", "last_name": "Doe", "age": 42})
        self.assertEqual(response.status_code, 200)
        
        # 5. Assert that the submission was saved in the database
        submission = form.submissions.first()
        self.assertIsNotNone(submission)
        self.assertEqual(submission.data["first_name"], "John")
        self.assertEqual(submission.data["last_name"], "Doe")
        self.assertEqual(submission.data["age"], "42")

    def test_public_endpoint_supports_cors_preflight(self):
        form = self.create_form(public_embed_enabled=True)
        endpoint = form.submit_api_url

        response = self.client.options(
            endpoint,
            HTTP_ORIGIN="https://example.com",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        self.assertIn("POST", response["Access-Control-Allow-Methods"])
        self.assertEqual(response["Access-Control-Allow-Headers"], "content-type")

    def test_public_endpoint_accepts_json_submission(self):
        form = self.create_form(public_embed_enabled=True)
        endpoint = form.submit_api_url

        response = self.client.post(
            endpoint,
            data=json.dumps({"first_name": "David", "last_name": "Bloomer", "age": 42}),
            content_type="application/json",
            HTTP_ORIGIN="https://example.com",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Access-Control-Allow-Origin"], "*")
        submission = form.submissions.first()
        self.assertIsNotNone(submission)
        self.assertEqual(submission.data["first_name"], "David")
        self.assertEqual(submission.data["last_name"], "Bloomer")
        self.assertEqual(submission.data["age"], 42)
    

from typing import Optional
from django.test import RequestFactory
from bloomerp.field_types import Lookup
from bloomerp.models import ContentType, User
from django.urls import reverse

from ..base import BaseBloomerpModelTestCase
from bloomerp.components.global_search import global_search
from bs4 import BeautifulSoup
from bloomerp.models import Policy, RowPolicy, FieldPolicy, RowPolicyRule
from bloomerp.models import ApplicationField
from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model

class SearchResultsTests(BaseBloomerpModelTestCase):
    auto_create_customers = False
    auto_create_users = True
    
    def extendedSetup(self):
        self.factory = RequestFactory()
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.url = reverse('components_global_search')
    
    def get_request(self, query:str, user:Optional[User]=None):
        request = self.factory.get(self.url, {'q': query})
        request.user = user or self.admin_user
        return request
        
    def test_core(self):
        """
        Tests whether the global search view returns a 200 
        """        
        # Create a request with search query
        request = self.get_request('John')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
    
    # ----------------------------------
    # GENERAL SEARCH FUNCTIONALITY TESTS
    # i.e. using no prefix
    # ----------------------------------
    def test_general_search_as_admin(self):
        """
        Tests whether general search works for an admin user.
        """
        # Create two customers, one matching the search query and one not
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        cust2 = self.create_customer(first_name='Jane', last_name='Smith', age=25)
        
        # Create a request with search query
        request = self.get_request('Grenit Xhaka')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results and the non-matching one is not
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        
        # Using __str__ representation of the customer to check if it's in the results, since the search result template uses that to display results
        self.assertIn(cust1.__str__(), soup.get_text())
        self.assertNotIn(cust2.__str__(), soup.get_text())
        
    def test_general_search_as_normal_user_without_permission(self):
        """
        Tests whether general search returns no results for a normal user without permissions.
        """
        # Create two customers, one matching the search query and one not
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        cust2 = self.create_customer(first_name='Jane', last_name='Smith', age=25)
        
        # Create a request with search query
        request = self.get_request('Grenit Xhaka', user=self.normal_user)
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that no results are returned
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertNotIn(cust1.__str__(), soup.get_text())
        self.assertNotIn(cust2.__str__(), soup.get_text())
    
    def test_general_search_as_normal_user_with_permission(self):
        """
        Tests whether general search returns results for a normal user with permissions.
        """
        # Create two customers, one matching the search query and one not
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        cust2 = self.create_customer(first_name='Jane', last_name='Smith', age=25)
        
        # Give normal user permission to view customers
        af = ApplicationField.get_for_model(self.CustomerModel).filter(field="first_name").first()
        permissions = Permission.objects.filter(content_type=self.content_type)
        
        # Create the permission
        field_policy = FieldPolicy.objects.create(
            content_type=self.content_type,
            name="field policy",
            rule={
                str(af.id):[
                    permissions.first().codename
                ]
            }
        )
        
        row_policy = RowPolicy.objects.create(
            content_type=self.content_type,
            name="row policy",
        )
        
        row_policy_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "application_field_id": af.id,
                "value": "Grenit",
                "operator": Lookup.EQUALS.value
            }
        )
        
        row_policy_rule.permissions.set(permissions)
        
        policy = Policy.objects.create(
            name='Test Policy', 
            row_policy=row_policy,
            field_policy=field_policy
        )
        
        policy.assign_user(self.normal_user)
        
        # Create a request with search query
        request = self.get_request('Grenit Xhaka', user=self.normal_user)
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results and the non-matching one is not
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        self.assertNotIn(cust2.__str__(), soup.get_text())
        
    # ----------------------------------
    # MODULE SPECIFIC SEARCH
    # i.e. using / prefix
    # ----------------------------------
    def test_module_specific_search_with_valid_module_and_model(self):
        """
        Tests whether module specific search returns results for a valid query.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/misc/customer/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_valid_module_and_invalid_model(self):
        """
        Tests whether module specific search returns no results for an invalid model.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/misc/invalidmodel/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that no results are returned
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertNotIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_invalid_module_and_model(self):
        """
        Tests whether module specific search returns no results for an invalid module and model.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/whatever/invalidmodel/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that no results are returned
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertNotIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_partial_module_and_full_model(self):
        """
        Tests whether module specific search returns results for a query with partial module and full model.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/mi/customer/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_full_module_and_partial_model(self):
        """
        Tests whether module specific search returns results for a query with full module and partial model.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/misc/cust/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_partial_module_and_partial_model(self):
        """
        Tests whether module specific search returns results for a query with partial module and partial model.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/mi/cust/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_valid_module_and_model_but_no_results(self):
        """
        Tests whether module specific search returns no results for a valid module and model but no matching results.
        """
        # Create a customer not matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/misc/customer/Nonexistent')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that no results are returned
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertNotIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_no_module_but_model(self):
        """
        Tests whether module specific search returns results for a query with no module but valid model.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('//customer/Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_no_module_and_no_model(self):
        """
        Tests whether module specific search returns results for a query with no module and no model, which should be treated as a general search.
        
        NOTE: we expect this to work the same as general search
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('///Grenit')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())
        
    def test_module_specific_search_with_full_query(self):
        """
        Tests whether module specific search works when the full query is provided.
        """
        # Create a customer matching the search query
        cust1 = self.create_customer(first_name='Grenit', last_name='Xhaka', age=30)
        
        # Create a request with search query
        request = self.get_request('/misc/customer/Grenit Xhaka')
        
        # Call the global search view
        response = global_search(request)
        
        # Check response status code
        self.assertEqual(response.status_code, 200)
        
        # Check that the matching customer is in the results
        results = response.content.decode('utf-8')
        soup = BeautifulSoup(results, 'html.parser')
        self.assertIn(cust1.__str__(), soup.get_text())

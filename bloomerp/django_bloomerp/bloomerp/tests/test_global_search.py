
from typing import Optional
from django.test import TestCase, RequestFactory
from bloomerp.models import ContentType, User
from django.urls import reverse
from .base import BaseBloomerpModelTestCase
from bloomerp.components.global_search import global_search

class SearchResultsTests(BaseBloomerpModelTestCase):
    def extendedSetup(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='12345', is_superuser=True)
        self.content_type = ContentType.objects.create(app_label='test_app', model='testmodel')
        self.url = reverse('components_global_search')
    
    def get_request(self, query:str, user:Optional[User]=None):
        request = self.factory.get(self.url, {'q': query})
        request.user = user or self.user
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
        
        
    
    

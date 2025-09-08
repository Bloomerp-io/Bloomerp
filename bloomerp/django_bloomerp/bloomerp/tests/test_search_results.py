
from django.test import TestCase, RequestFactory
from bloomerp.models import Link, ContentType, User
from bloomerp.components.search_results import search_results
from django.urls import reverse

class SearchResultsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='12345', is_superuser=True)
        self.content_type = ContentType.objects.create(app_label='test_app', model='testmodel')
        Link.objects.create(name='Test Link', url='test/url', level='LIST', content_type=self.content_type)
        self.url = reverse('components_search_results')


    def test_no_query_provided(self):
        request = self.factory.get(self.url)
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No query provided', response.content)

    def test_list_level_links(self):
        request = self.factory.get(self.url, {'search_results_query': '/testmodel'})
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Test Link', response.content)

    def test_app_level_links(self):
        Link.objects.create(name='App Link', url='app/url', level='APP')
        request = self.factory.get(self.url, {'search_results_query': '//A'})
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'App Link', response.content)

    def test_model_string_search(self):
        # Assuming your model has a string_search method
        request = self.factory.get(self.url, {'search_results_query': 'test'})
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        # Add more assertions based on your model's string_search results
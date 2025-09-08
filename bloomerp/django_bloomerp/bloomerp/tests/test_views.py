
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from bloomerp.views.core import BloomerpListView, BloomerpDetailOverviewView

class BloomerpViewsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(username='testuser', password='12345')

    def test_bloomerp_list_view(self):
        request = self.factory.get('/list')
        request.user = self.user
        response = BloomerpListView.as_view()(request)
        self.assertEqual(response.status_code, 200)

    def test_bloomerp_detail_overview_view(self):
        request = self.factory.get('/overview')
        request.user = self.user
        response = BloomerpDetailOverviewView.as_view()(request)
        self.assertEqual(response.status_code, 200)
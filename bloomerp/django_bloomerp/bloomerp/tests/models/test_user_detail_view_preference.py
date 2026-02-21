from django.test import RequestFactory

from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models import UserDetailViewPreference
from django.contrib.contenttypes.models import ContentType
from bloomerp.router import router

class DetailViewTabsTestCase(BaseBloomerpModelTestCase):
    
    def test_automatically_create_tabs(self):
        """
        Tests whether detail view tabs are automatically created for users that don't have any tabs yet
        for a particular model.
        """        
        # 1. Get a random object and its detail view URL
        obj = self.CustomerModel.objects.first()
        url = obj.get_absolute_url()
        
        # 2. Check whether the user has any detail view preferences for this model (there should be none)
        detail_view_preference = UserDetailViewPreference.objects.filter(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel)
        ).first()
        self.assertIsNone(detail_view_preference)
        
        # 3. Simulate a request to the detail view URL with the admin user and check whether detail view preferences are created
        self.factory = RequestFactory()
        request = self.factory.get(url)
        request.user = self.admin_user
        self.client.force_login(self.admin_user)
        response = self.client.get(url)
        
        # 4. Check whether detail view preferences are created for the user and model
        detail_view_preference = UserDetailViewPreference.objects.filter(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel)
        ).first()
        self.assertIsNotNone(detail_view_preference)
        
        # 5. Check whether the created detail view preferences have the default tabs
        self.assertTrue(len(detail_view_preference.tab_state_obj.get("top_level_order")) > 0)
        
        
    def test_non_existant_url_name_should_not_return_500(self):
        """
        Tests whether a non-existant URL name in the tabs configuration raises an error or is just ignored.
        """
        # 1. Create detail view preferences for the admin user and CustomerModel with a non-existant URL name in the tab configuration
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field_layout={},
            tab_state={
                "version": 2,
                "top_level_order": ["non_existant_tab"],
                "folders": [],
                "active": None,
            }
        )
        
        # 2. Simulate a request to the detail view URL with the admin user and check whether it returns a 200 status code (instead of a 500)
        obj = self.CustomerModel.objects.first()
        url = obj.get_absolute_url()
        
        self.factory = RequestFactory()
        request = self.factory.get(url)
        request.user = self.admin_user
        self.client.force_login(self.admin_user)
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)

    def test_tab_state_obj_normalizes_legacy_v1_shape(self):
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field_layout={},
            tab_state={
                "order": ["overview"],
                "active": "overview",
            },
        )

        self.assertEqual(detail_view_preference.tab_state_obj.get("version"), 2)
        self.assertEqual(detail_view_preference.tab_state_obj.get("top_level_order"), ["overview"])
        self.assertEqual(detail_view_preference.tab_state_obj.get("folders"), [])

    def test_tab_state_obj_defaults_for_invalid_state(self):
        detail_view_preference = UserDetailViewPreference.objects.create(
            user=self.admin_user,
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            field_layout={},
            tab_state="invalid",
        )

        self.assertEqual(detail_view_preference.tab_state_obj.get("version"), 2)
        self.assertEqual(detail_view_preference.tab_state_obj.get("top_level_order"), [])
        self.assertEqual(detail_view_preference.tab_state_obj.get("folders"), [])
        self.assertIsNone(detail_view_preference.tab_state_obj.get("active"))
        
    
    
    
    
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.test import TransactionTestCase
from django.urls import reverse

from bloomerp.management.commands import save_application_fields
from bloomerp.models.users import User
from bloomerp.models.users.user_list_view_preference import PageSize, UserListViewPreference
from bloomerp.tests.utils.dynamic_models import create_test_models


class TestDataViewPagination(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": {
                    "name": models.CharField(max_length=100),
                    "age": models.IntegerField(),
                }
            },
            use_bloomerp_base=True,
        )["Customer"]

    def setUp(self):
        super().setUp()
        save_application_fields.Command().handle()

        self.user = User.objects.create(
            username="pagination_user",
            password="password12345",
            is_superuser=True,
            is_staff=True,
        )

        for i in range(21):
            self.CustomerModel.objects.create(
                name=f"Customer {i}",
                age=i,
                created_by=self.user,
            )

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        preference, _ = UserListViewPreference.objects.get_or_create(
            user=self.user,
            content_type=content_type,
        )
        preference.page_size = PageSize.SIZE_10
        preference.save()

    def tearDown(self):
        try:
            self.CustomerModel.objects.all().delete()
        finally:
            super().tearDown()

    def test_pagination_controls_render_in_dataview(self):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("components_data_view", kwargs={"content_type_id": content_type.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-testid="data-view-pagination"')
        self.assertContains(response, "Page 1 of 3")
        self.assertContains(response, "page=2")

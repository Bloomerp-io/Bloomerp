from django.test import TransactionTestCase
from django.db import models
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.models.users import User


class TestUserPermissionManager(TransactionTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # 1. Create isolated test model (NOT bloomerp)
        cls.CustomerModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "Customer": {
                    "first_name": models.CharField(max_length=100),
                    "last_name": models.CharField(max_length=100),
                }
            }
        )["Customer"]

        # 2. Create users
        cls.admin_user = User.objects.create(
            username="U1",
            password="password12345",
            is_superuser=True,
            is_staff=True,
        )

        cls.normal_user = User.objects.create(
            username="U2",
            password="password12345",
        )

        # 3. Create objects
        for i in range(10):
            cls.CustomerModel.objects.create(
                first_name=f"Jaimy {i}",
                last_name=f"Fuller {i}",
            )

    def test_something(self):
        qs = self.CustomerModel.objects.all()
        self.assertEqual(qs.count(), 10)

from bloomerp.models import Policy, FieldPolicy, RowPolicy, RowPolicyRule
from bloomerp.models.application_field import ApplicationField
from bloomerp.services.permission_services import UserPermissionManager
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group
from bloomerp.field_types import Lookup
from bloomerp.tests.base import BaseBloomerpModelTestCase

class TestUserPermissionManager(BaseBloomerpModelTestCase):
    auto_create_customers = False
    create_foreign_models = True
    
    def extendedSetup(self):
        # 2. Create objects
        for i in range(10):
            # 2 Records for Belgium
            # 3 Records for Helvetia
            if i in [0,1]:
                created_by = self.normal_user
                country=self.CountryModel.objects.filter(name="Belgium").first()
            elif i in [2,3,4]:
                created_by = self.admin_user
                country=self.CountryModel.objects.filter(name="Helvetia").first()
            else:
                created_by = self.admin_user
                country=self.CountryModel.objects.filter(name="Brazil").first()
            
            
            self.CustomerModel.objects.create(
                first_name=f"Jaimy {i}",
                last_name=f"Fuller {i}",
                created_by=created_by,
                age=i,
                country=country
            )
        
        # Get the
        ct = ContentType.objects.get_for_model(self.CustomerModel)
        self.customer_model_fields = ApplicationField.get_for_content_type_id(ct.id)
        
        self.first_name_field = self.customer_model_fields.filter(field="first_name").first()
        self.last_name_field = self.customer_model_fields.filter(field="last_name").first()
        self.age_field = self.customer_model_fields.filter(field="age").first()
        self.country_field = self.customer_model_fields.filter(field="country").first()
        
        # Create policies
        self.field_policy = FieldPolicy.objects.create(
            content_type=ct,
            name="field policy",
            rule={
                str(self.first_name_field.id):[
                    "view_customer"
                ]
            }
        )

        self.row_policy = RowPolicy.objects.create(
            content_type=ct,
            name="Row policy"
        )

        self.policy = Policy.objects.create(
            name="Policy",
            description="A cool policy",
            row_policy=self.row_policy,
            field_policy=self.field_policy
        )


    def tearDown(self):
        # The dynamic Customer model is created under an app_label that isn't
        # in INSTALLED_APPS, so Django's flush won't clear its table. If it
        # still contains rows referencing auth_user, the flush can fail on
        # SQLite foreign key constraints.
        try:
            self.CustomerModel.objects.all().delete()
        finally:
            super().tearDown()
        

    def test_admin_has_access_to_field(self):
        """
        This test is there to show that an admin/superuser always has
        access to a particular field.
        """
        # 1. Construct the manager
        manager = UserPermissionManager(self.admin_user)
        
        # 2. Check if the admin has access to this field
        for perm in self.CustomerModel._meta.default_permissions:
            for field in self.customer_model_fields:
                self.assertTrue(manager.has_field_permission(field, f"{perm}_customer"))

        
    def test_normal_user_has_access_to_field(self):
        """
        This test is there to check whether a regular user has access to a
        particular field.
        """
        # 1. Construct the manager
        manager = UserPermissionManager(self.normal_user)
        
        # 2. Check if the admin has access to this field
        for perm in self.CustomerModel._meta.default_permissions:
            for field in self.customer_model_fields:
                self.assertFalse(manager.has_field_permission(self.first_name_field, f"{perm}_customer"))
    
    
    def test_normal_user_has_access_to_field_after_assignment(self):
        """
        This test is there to check if a user has access to a
        field after assignment
        """
        # 1. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 2. Construct the manager
        manager = UserPermissionManager(self.normal_user)
        
        # 3. Check if the user has access
        self.assertTrue(manager.has_field_permission(self.first_name_field, f"view_customer"))
        
        # 4. Check if others are not true
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view":
                continue
            self.assertFalse(manager.has_field_permission(self.first_name_field, f"{perm}_customer"))
        
        # 5. Check if other fields remain inaccessible
        custom_qs = self.customer_model_fields.exclude(id=self.first_name_field.id)
        for perm in self.CustomerModel._meta.default_permissions:
            for field in custom_qs:
                self.assertFalse(manager.has_field_permission(field, f"{perm}_customer"))
        

    def test_normal_user_has_access_to_field_after_group_assignment(self):
        """
        This test checks whether a user has access to 
        a field using the groups.
        """
        # 1. Create a group
        group = Group.objects.create(
            name="Cool group"
        )
        
        # 2. Assign a group
        self.policy.assign_group(group)
        
        # 3. Assign a user to a group
        self.normal_user.groups.add(group)
        
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has access
        self.assertTrue(manager.has_field_permission(self.first_name_field, f"view_customer"))
        
        # 5. Check if others are not true
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view":
                continue
            self.assertFalse(manager.has_field_permission(self.first_name_field, f"{perm}_customer"))
        
        # 6. Check if other fields remain inaccessible
        custom_qs = self.customer_model_fields.exclude(id=self.first_name_field.id)
        for perm in self.CustomerModel._meta.default_permissions:
            for field in custom_qs:
                self.assertFalse(manager.has_field_permission(field, f"{perm}_customer"))
        
        
    def test_admin_accessible_fields(self):
        """
        This test checks whether the admin permission manager
        returns all accessible fields.
        """
        # 1. Construct the manager
        manager = UserPermissionManager(self.admin_user)
        
        # 2. Get the accessible fields
        accessible_fields = manager.get_accessible_fields(
            ContentType.objects.get_for_model(self.CustomerModel),
            "view_customer"
        )
        
        # 3. Check that all fields are returned
        self.assertEqual(accessible_fields.count(), self.customer_model_fields.count())
    
        
    def test_normal_user_accessible_fields(self):
        """
        This test checks whether the user permission manager
        returns the correct accessible fields.
        """
        # 1. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 2. Construct the manager
        manager = UserPermissionManager(self.normal_user)
        
        # 3. Get the accessible fields
        accessible_fields = manager.get_accessible_fields(
            ContentType.objects.get_for_model(self.CustomerModel),
            "view_customer"
        )
        
        # 4. Check that only the first_name_field is returned
        self.assertEqual(accessible_fields.count(), 1)
        self.assertEqual(accessible_fields.first(), self.first_name_field)
        
    
    # --------------------------------------
    # Test Row Policies
    # --------------------------------------
    def test_admin_has_access_to_queryset(self):
        """
        This tests whether an admin has access to 
        the entire queryset even if no permission has
        been assigned.
        """
        # 1. Construct the user manager
        manager = UserPermissionManager(self.admin_user)
        
        # 2. Get the full length of the queryset
        nr_of_records = self.CustomerModel.objects.all().count()
        
        # 3. Check if the user has all levels of access to all objects
        for perm in self.CustomerModel._meta.default_permissions:
            self.assertEqual(manager.get_queryset(self.CustomerModel, f"{perm}_customer").count(), nr_of_records)
        
        
    def test_normal_user_has_no_access_to_queryset(self):
        """
        This tests whether a normal user has no access to
        the queryset if no policy assignment has been done.
        """
        # 1. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 2. Check if the user has all levels of access to all objects
        for perm in self.CustomerModel._meta.default_permissions:
            self.assertEqual(manager.get_queryset(self.CustomerModel, f"{perm}_customer").count(), 0)
            
            
    def test_normal_user_has_no_access_to_queryset_after_assignment_without_rules(self):
        """
        This tests whether a normal user has no access to
        the queryset if a policy assignment has been done
        but no rules exist.
        """
        # 1. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 2. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 3. Check if the user has all levels of access to all objects
        for perm in self.CustomerModel._meta.default_permissions:
            self.assertEqual(manager.get_queryset(self.CustomerModel, f"{perm}_customer").count(), 0)
            
    
    def test_normal_user_has_access_to_queryset_after_assignment_with_rules(self):
        """
        This tests whether a normal user has access to
        the queryset if a policy assignment has been done
        with rules.
        """
        # 1. Create a row policy rule
        for i in range(2):
            row_policy = RowPolicyRule.objects.create(
                row_policy=self.row_policy,
                rule={
                    "application_field_id" : str(self.first_name_field.id),
                    "operator" : Lookup.EQUALS.value.id,
                    "value" : f"Jaimy {i}"
                }
            )
            
            row_policy.add_permission("view_customer")
            
        
        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 3. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has all levels of access to all objects
        qs = manager.get_queryset(self.CustomerModel, f"view_customer")
        self.assertEqual(qs.count(), 2)
        
        # 5. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_product")
            self.assertEqual(qs.count(), 0)
            
    
    def test_normal_user_has_access_to_queryset_with_user_rule(self):
        """
        This tests whether a normal user has access to
        a queryset using a row policy rule that references
        a user
        """
        # 1. Create a row policy rule
        application_field_id = ApplicationField.get_for_model(
            self.CustomerModel
        ).filter(
            field="created_by"
        ).first().id
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id" : application_field_id,
                "operator" : Lookup.EQUALS_USER.value.id,
                "value" : f"$user"
            }
        )
        
        row_policy.add_permission("view_customer")
            
        
        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 3. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has all levels of access to all objects
        qs = manager.get_queryset(self.CustomerModel, f"view_customer")
        self.assertEqual(qs.count(), 2)
        
        # 5. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_customer")
            self.assertEqual(qs.count(), 0)
            
            
    def test_normal_user_has_access_to_queryset_with_contains_operator(self):
        """
        This test will check whether the contain operator
        works
        """
        # 1. Create a row policy rule
        for i in range(2):
            row_policy = RowPolicyRule.objects.create(
                row_policy=self.row_policy,
                rule={
                    "application_field_id" : str(self.first_name_field.id),
                    "operator" : Lookup.CONTAINS.value.id,
                    "value" : f"1"
                }
            )
            
            row_policy.add_permission("view_customer")
            
        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 3. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has all levels of access to all objects
        qs = manager.get_queryset(self.CustomerModel, f"view_customer")
        self.assertEqual(qs.count(), 1)
        
        # 5. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_product")
            self.assertEqual(qs.count(), 0)
            
            
    def test_normal_user_has_access_to_queryset_with_gte_operator(self):
        # 1. Create a row policy rule
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id" : str(self.age_field.id),
                "operator" : Lookup.GREATER_THAN_OR_EQUAL.value.id,
                "value" : 5
            }
        )
            
        row_policy.add_permission("view_customer")
            
        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 3. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has all levels of access to all objects
        qs = manager.get_queryset(self.CustomerModel, f"view_customer")
        self.assertEqual(qs.count(), 5)
        
        # 5. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_product")
            self.assertEqual(qs.count(), 0)
    
    
    def test_normal_user_has_access_with_foreign_field_operator(self):
        """
        Tests whether a normal user has access to objects with a foreign
        field operator (i.e. using the country field)
        """
        # 1. Create a row policy rule
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id" : str(self.country_field.id),
                "operator" : "__country__name",
                "value" : "Belgium"
            }
        )
        
        row_policy.add_permission("view_customer")
            
        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 3. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has all levels of access to all objects
        qs = manager.get_queryset(self.CustomerModel, f"view_customer")
        self.assertEqual(qs.count(), 2)
        
        # 5. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_product")
            self.assertEqual(qs.count(), 0)
           
            
    def test_normal_user_has_access_with_nested_foreign_field_operator(self):
        """
        Tests whether a normal user has access to objects with a foreign
        field operator (i.e. using the planet field of the country field)
        """
        # 1. Create a row policy rule
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id" : str(self.country_field.id),
                "operator" : "__country__planet__name",
                "value" : "Mars"
            }
        )
        
        row_policy.add_permission("view_customer")
            
        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)
        
        # 3. Construct the user manager
        manager = UserPermissionManager(self.normal_user)
        
        # 4. Check if the user has all levels of access to all objects
        qs = manager.get_queryset(self.CustomerModel, f"view_customer")
        self.assertEqual(qs.count(), 3)
        
        # 5. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_product")
            self.assertEqual(qs.count(), 0)
            
    

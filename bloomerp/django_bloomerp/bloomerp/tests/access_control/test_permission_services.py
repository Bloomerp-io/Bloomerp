from bloomerp.models import Policy, FieldPolicy, RowPolicy, RowPolicyRule
from bloomerp.models.application_field import ApplicationField
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.utils.api import generate_model_viewset_class, generate_serializer
from bloomerp.views.api_views import BloomerpModelViewSet
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group, Permission
from bloomerp.field_types import Lookup
from bloomerp.tests.base import BaseBloomerpModelTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

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
        
        # Ensure permissions exist for the dynamically created model
        self._ensure_permissions_for_model(self.CustomerModel)

        # Build an API viewset + request factory for API-level tests
        self.ApiViewSet = generate_model_viewset_class(
            model=self.CustomerModel,
            serializer=generate_serializer(self.CustomerModel),
            base_viewset=BloomerpModelViewSet,
        )
        self.factory = APIRequestFactory()

    def _ensure_permissions_for_model(self, model):
        """Create default permissions for dynamic models (if missing)."""
        content_type = ContentType.objects.get_for_model(model)
        for perm in model._meta.default_permissions:
            codename = f"{perm}_{model._meta.model_name}"
            Permission.objects.get_or_create(
                codename=codename,
                content_type=content_type,
                defaults={"name": f"Can {perm} {model._meta.verbose_name}"},
            )

    def _extract_results(self, response):
        """Helper to normalize paginated vs. non-paginated responses."""
        if isinstance(response.data, dict) and "results" in response.data:
            return response.data["results"]
        return response.data


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


    def test_normal_user_has_access_to_queryset_with_not_equals_operator(self):
        """
        This test checks that the not-equals operator is translated to a
        negated exact filter rather than an invalid Django lookup.
        """
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(self.last_name_field.id),
                "operator": Lookup.NOT_EQUALS.value.id,
                "value": "Fuller 0",
            },
        )

        row_policy.add_permission("view_customer")
        self.policy.assign_user(self.normal_user)

        manager = UserPermissionManager(self.normal_user)
        qs = manager.get_queryset(self.CustomerModel, "view_customer")

        self.assertEqual(qs.count(), 9)
        self.assertFalse(qs.filter(last_name="Fuller 0").exists())
    
    
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

    def test_candidate_matches_add_row_policy_for_direct_field(self):
        # TODO: Add laymen description of what this test actually does
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(self.first_name_field.id),
                "operator": Lookup.EQUALS.value.id,
                "value": "Allowed",
            },
        )
        row_policy.add_permission("add_customer")
        self.policy.assign_user(self.normal_user)

        manager = UserPermissionManager(self.normal_user)

        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Allowed",
                    "last_name": "Person",
                    "age": 30,
                },
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Blocked",
                    "last_name": "Person",
                    "age": 30,
                },
            )
        )

    def test_candidate_matches_add_row_policy_with_equals_user(self):
        created_by_field = ApplicationField.get_for_model(self.CustomerModel).filter(field="created_by").first()
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(created_by_field.id),
                "operator": Lookup.EQUALS_USER.value.id,
                "value": "$user",
            },
        )
        row_policy.add_permission("add_customer")
        self.policy.assign_user(self.normal_user)

        manager = UserPermissionManager(self.normal_user)

        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Allowed",
                    "last_name": "Person",
                    "age": 30,
                },
            )
        )

    def test_candidate_matches_add_row_policy_with_nested_foreign_field(self):
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(self.country_field.id),
                "operator": "__country__planet__name",
                "value": "Earth",
            },
        )
        row_policy.add_permission("add_customer")
        self.policy.assign_user(self.normal_user)

        manager = UserPermissionManager(self.normal_user)

        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Allowed",
                    "last_name": "Person",
                    "age": 30,
                    "country": self.CountryModel.objects.get(name="Belgium"),
                },
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Allowed",
                    "last_name": "Person",
                    "age": 30,
                    "country": self.CountryModel.objects.get(name="Helvetia"),
                },
            )
        )

    # --------------------------------------
    # API tests using RequestFactory
    # --------------------------------------
    def test_api_list_respects_row_and_field_permissions(self):
        """
        GET list should:
        - return only rows allowed by row policy
        - include only fields allowed by field policy
        """
        # 1. Create a row policy rule that matches a single record
        target = self.CustomerModel.objects.first()
        row_rule = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(self.first_name_field.id),
                "operator": Lookup.EQUALS.value.id,
                "value": target.first_name,
            },
        )
        row_rule.add_permission("view_customer")

        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)

        # 3. Call the auto-generated list endpoint
        request = self.factory.get("/api/customers/")
        force_authenticate(request, user=self.normal_user)

        view = self.ApiViewSet.as_view({"get": "list"})
        response = view(request)
        
        # 4. Validate row + field permissions
        self.assertEqual(response.status_code, 200)
        results = self._extract_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("first_name"), target.first_name)
        self.assertNotIn("last_name", results[0])
        self.assertIn("first_name", results[0])


    def test_api_update_denies_disallowed_field(self):
        """
        PATCH should fail when writing to a field without change permission.
        """
        # 1. Allow row-level access for change
        target = self.CustomerModel.objects.first()
        row_rule = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(self.first_name_field.id),
                "operator": Lookup.EQUALS.value.id,
                "value": target.first_name,
            },
        )
        row_rule.add_permission("change_customer")

        # 2. Assign the user to the policy
        self.policy.assign_user(self.normal_user)

        # 3. Attempt to update a disallowed field
        request = self.factory.patch(
            f"/api/customers/{target.id}/",
            {"last_name": "Blocked"},
            format="json",
        )
        force_authenticate(request, user=self.normal_user)

        view = self.ApiViewSet.as_view({"patch": "partial_update"})
        response = view(request, pk=str(target.id))

        self.assertEqual(response.status_code, 403)


    def test_api_update_allows_allowed_field(self):
        """
        PATCH should succeed when writing to a field with change permission.
        """
        # 1. Allow row-level access for change
        target = self.CustomerModel.objects.first()
        row_rule = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule={
                "application_field_id": str(self.first_name_field.id),
                "operator": Lookup.EQUALS.value.id,
                "value": target.first_name,
            },
        )
        row_rule.add_permission("change_customer")

        # 2. Allow field-level change permission on first_name
        rules = self.field_policy.rule or {}
        rules.setdefault(str(self.first_name_field.id), [])
        if "change_customer" not in rules[str(self.first_name_field.id)]:
            rules[str(self.first_name_field.id)].append("change_customer")
        self.field_policy.rule = rules
        self.field_policy.save(update_fields=["rule"])

        # 3. Assign the user to the policy
        self.policy.assign_user(self.normal_user)

        # 4. Update an allowed field
        request = self.factory.patch(
            f"/api/customers/{target.id}/",
            {"first_name": "Allowed"},
            format="json",
        )
        force_authenticate(request, user=self.normal_user)

        view = self.ApiViewSet.as_view({"patch": "partial_update"})
        response = view(request, pk=str(target.id))

        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.first_name, "Allowed")
            
    
    # --------------------------------------
    # SQL Query
    # --------------------------------------
    

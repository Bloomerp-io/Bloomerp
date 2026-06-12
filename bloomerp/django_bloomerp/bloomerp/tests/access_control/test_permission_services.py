from django.test import override_settings

from bloomerp.config.definition import ApiKeyAuthSettings, BloomerpAuthSettings, BloomerpConfig
from bloomerp.models import ApiKey, Policy, FieldPolicy, RowPolicy, RowPolicyRule
from bloomerp.models.access_control.row_policy_rule import RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.models.application_field import ApplicationField
from bloomerp.models.definition import (
    ApiFilterRule,
    ApiNesting,
    ApiSettings,
    BloomerpModelConfig,
    PublicAccessRule,
    UserAccessRule,
)
from bloomerp.services.permission_services import UserPermissionManager
from bloomerp.utils.api import generate_model_viewset_class, generate_serializer
from bloomerp.views.api.api_views import BloomerpModelViewSet
from bloomerp.models.users import User
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group, Permission
from bloomerp.field_types.lookups import Lookup
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
        self._ensure_permissions_for_model(self.CountryModel)
        self._ensure_permissions_for_model(self.PlanetModel)

        # Build an API viewset + request factory for API-level tests
        self.ApiViewSet = generate_model_viewset_class(
            model=self.CustomerModel,
            serializer=generate_serializer(self.CustomerModel),
            base_viewset=BloomerpModelViewSet,
        )
        self.CountryApiViewSet = generate_model_viewset_class(
            model=self.CountryModel,
            serializer=generate_serializer(self.CountryModel),
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

    def _set_public_access(self, *rules: PublicAccessRule):
        previous = getattr(self.CustomerModel, "bloomerp_config", None)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                public_access=list(rules),
            )
        )
        return previous

    def _restore_public_access(self, previous):
        if previous is None:
            try:
                delattr(self.CustomerModel, "bloomerp_config")
            except AttributeError:
                pass
            return
        self.CustomerModel.bloomerp_config = previous

    def _set_user_access(self, *rules: UserAccessRule):
        previous = getattr(self.CustomerModel, "bloomerp_config", None)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                user_access=list(rules),
            )
        )
        return previous

    def _set_model_public_access(self, model, *rules: PublicAccessRule, nesting=None):
        previous = getattr(model, "bloomerp_config", None)
        model.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                public_access=list(rules),
                nesting=list(nesting or []),
            )
        )
        return previous

    def _set_model_user_access(self, model, *rules: UserAccessRule):
        previous = getattr(model, "bloomerp_config", None)
        model.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                user_access=list(rules),
            )
        )
        return previous

    def _restore_model_config(self, model, previous):
        if previous is None:
            try:
                delattr(model, "bloomerp_config")
            except AttributeError:
                pass
            return
        model.bloomerp_config = previous

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
            rule = RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(self.first_name_field.id),
                        operator=Lookup.EQUALS.value.id,
                        value=f"Jaimy {i}"
                    )
                ]
            )
            
            row_policy = RowPolicyRule.objects.create(
                row_policy=self.row_policy,
                rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(application_field_id),
                        operator=Lookup.EQUALS_USER.value.id,
                        value="$user"
                    )
                ]
            )
        
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
            rule = RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(self.first_name_field.id),
                        operator=Lookup.CONTAINS.value.id,
                        value="1"
                    )
                ]
            )

            row_policy = RowPolicyRule.objects.create(
                row_policy=self.row_policy,
                rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.age_field.id),
                    operator=Lookup.GREATER_THAN_OR_EQUAL.value.id,
                    value=5
                )
            ]
        )
        
        # 1. Create a row policy rule
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.last_name_field.id),
                    operator=Lookup.NOT_EQUALS.value.id,
                    value="Fuller 0"
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.country_field.id),
                    operator="__country__name",
                    value="Belgium"
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.country_field.id),
                    operator="__country__planet__name",
                    value="Mars"
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
        """
        This test checks whether the candidate_matches_row_policies method correctly checks row policies for the add action, which don't have an instance and thus require checking the candidate data against the row policy rules.
        
        Example for when this is used:
        - User wants to add a new customer with particular data
        - this data needs to adhere to the policies for the user
        """
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.first_name_field.id),
                    operator=Lookup.EQUALS.value.id,
                    value="Allowed"
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(created_by_field.id),
                    operator=Lookup.EQUALS_USER.value.id,
                    value="$user"
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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
        rule = RowPolicyRuleContent(
            connector="OR",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.country_field.id),
                    operator="__country__planet__name",
                    value="Earth"
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
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

    def test_candidate_matches_add_row_policy_with_and_rule_and_direct_foreign_key(self):
        """
        Create checks should match grouped rules where one condition targets a
        regular value and another targets a direct foreign key selected by id.
        """
        country = self.CountryModel.objects.get(name="Belgium")
        other_country = self.CountryModel.objects.get(name="Helvetia")
        rule = RowPolicyRuleContent(
            connector="AND",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.last_name_field.id),
                    operator=Lookup.EQUALS.value.id,
                    value="Peeters",
                ),
                RowPolicyRuleCondition(
                    application_field_id=str(self.country_field.id),
                    operator=Lookup.FOREIGN_EQUALS.value.id,
                    value=str(country.pk),
                ),
            ],
        )

        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump(),
        )
        row_policy.add_permission("add_customer")
        self.policy.assign_user(self.normal_user)

        manager = UserPermissionManager(self.normal_user)

        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Jaimy",
                    "last_name": "Peeters",
                    "age": 30,
                    "country": country,
                },
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Jaimy",
                    "last_name": "Peeters",
                    "age": 30,
                    "country": other_country,
                },
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel,
                "add_customer",
                {
                    "first_name": "Jaimy",
                    "last_name": "Blocked",
                    "age": 30,
                    "country": country,
                },
            )
        )

    def test_user_can_view_all_objects_with_all_row_policy(self):
        """
        This test checks whether a user can view all object if the row policy has an all rule.
        The all rule is still bounded by the permissions assigned to the rule.
        """
        perm = "view_customer"

        # 1. Create a row policy rule
        rule = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        field="__all__"
                    )
                ]
            ).model_dump()
        )
        
        # 2. Assign permissions to the rule
        rule.add_permission(perm)

        # 3. Assign the user to the policy
        self.policy.assign_user(self.normal_user)

        # 4. Construct the user manager
        manager = UserPermissionManager(self.normal_user)

        # 5. Check if the user has access to all objects
        qs = manager.get_queryset(self.CustomerModel, perm)
        self.assertEqual(qs.count(), self.CustomerModel.objects.count())

        # 6. Check if the user has no other access
        for perm in self.CustomerModel._meta.default_permissions:
            if perm == "view": continue
            qs = manager.get_queryset(self.CustomerModel, f"{perm}_customer")
            self.assertEqual(qs.count(), 0)
        
    def test_user_can_view_objects_with_multiple_and_conditions(self):
        rule = RowPolicyRuleContent(
            connector="AND",
            conditions=[
                RowPolicyRuleCondition(
                    application_field_id=str(self.first_name_field.id),
                    operator=Lookup.CONTAINS.value.id,
                    value="Jaimy"
                ),
                RowPolicyRuleCondition(
                    application_field_id=str(self.age_field.id),
                    operator=Lookup.GREATER_THAN_OR_EQUAL.value.id,
                    value=5
                )
            ]
        )
        
        row_policy = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=rule.model_dump()
        )
        
        row_policy.add_permission("view_customer")
        self.policy.assign_user(self.normal_user)
        
        manager = UserPermissionManager(self.normal_user)
        qs = manager.get_queryset(self.CustomerModel, "view_customer")
        
        self.assertEqual(qs.count(), 5)
        self.assertTrue(all("Jaimy" in obj.first_name for obj in qs))
        self.assertTrue(all(obj.age >= 5 for obj in qs))

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
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(self.first_name_field.id),
                        operator=Lookup.EQUALS.value.id,
                        value=target.first_name,
                    )
                ]
            ).model_dump(),
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

    @override_settings(
        BLOOMERP_CONFIG=BloomerpConfig(
            auto_generate_api_endpoints=True,
            auth=BloomerpAuthSettings(
                api_key=ApiKeyAuthSettings(enabled=True),
            ),
        )
    )
    def test_api_key_list_uses_linked_account_permissions(self):
        target = self.CustomerModel.objects.first()
        row_rule = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(self.first_name_field.id),
                        operator=Lookup.EQUALS.value.id,
                        value=target.first_name,
                    )
                ],
            ).model_dump(),
        )
        row_rule.add_permission("view_customer")
        self.policy.assign_user(self.normal_user)

        api_key = ApiKey(account=self.normal_user, name="SDK key")
        raw_token = api_key.set_token()
        api_key.save()

        request = self.factory.get(
            "/api/customers/",
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )
        view = self.ApiViewSet.as_view({"get": "list"})
        response = view(request)

        self.assertEqual(response.status_code, 200)
        results = self._extract_results(response)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("first_name"), target.first_name)
        self.assertNotIn("last_name", results[0])

        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.last_used_at)

    def test_api_update_denies_disallowed_field(self):
        """
        PATCH should fail when writing to a field without change permission.
        """
        # 1. Allow row-level access for change
        target = self.CustomerModel.objects.first()
        row_rule = RowPolicyRule.objects.create(
            row_policy=self.row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(self.first_name_field.id),
                        operator=Lookup.EQUALS.value.id,
                        value=target.first_name,
                    )
                ]
            ).model_dump(),
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
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(self.first_name_field.id),
                        operator=Lookup.EQUALS.value.id,
                        value=target.first_name,
                    )
                ]
            ).model_dump(),
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

    # TODO: Review these test cases
    def test_api_list_allows_anonymous_public_access_with_filtered_rows_and_fields(self):
        previous = self._set_public_access(
            PublicAccessRule(
                row_actions=["list"],
                field_actions={
                    "id": ["list"],
                    "first_name": ["list"],
                },
                filters=[ApiFilterRule(field="age", operator=Lookup.GREATER_THAN_OR_EQUAL.value.id, value=8)],
            )
        )

        try:
            request = self.factory.get("/api/customers/")
            view = self.ApiViewSet.as_view({"get": "list"})
            response = view(request)

            self.assertEqual(response.status_code, 200)
            results = self._extract_results(response)
            self.assertEqual(len(results), 2)
            self.assertEqual({row["first_name"] for row in results}, {"Jaimy 8", "Jaimy 9"})
            self.assertTrue(all("first_name" in row for row in results))
            self.assertTrue(all("last_name" not in row for row in results))
            self.assertTrue(all("age" not in row for row in results))
        finally:
            self._restore_public_access(previous)

    def test_api_read_allows_anonymous_public_access_when_rule_uses_read_action(self):
        allowed = self.CustomerModel.objects.get(age=0)
        previous = self._set_public_access(
            PublicAccessRule(
                row_actions=["read"],
                field_actions={
                    "id": ["read"],
                    "first_name": ["read"],
                },
                filters=[ApiFilterRule(field="age", operator=Lookup.EQUALS.value.id, value=allowed.age)],
            )
        )

        try:
            request = self.factory.get(f"/api/customers/{allowed.pk}/")
            view = self.ApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(allowed.pk))

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["first_name"], allowed.first_name)
            self.assertNotIn("last_name", response.data)
            self.assertNotIn("age", response.data)
        finally:
            self._restore_public_access(previous)

    def test_api_read_returns_404_for_anonymous_when_object_is_outside_public_access_filter(self):
        allowed = self.CustomerModel.objects.get(age=0)
        blocked = self.CustomerModel.objects.get(age=1)
        previous = self._set_public_access(
            PublicAccessRule(
                row_actions=["read"],
                field_actions={
                    "id": ["read"],
                    "first_name": ["read"],
                },
                filters=[ApiFilterRule(field="age", operator=Lookup.EQUALS.value.id, value=allowed.age)],
            )
        )

        try:
            request = self.factory.get(f"/api/customers/{blocked.pk}/")
            view = self.ApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(blocked.pk))

            self.assertEqual(response.status_code, 404)
        finally:
            self._restore_public_access(previous)

    def test_api_read_nests_foreign_key_when_declared_and_related_model_is_public(self):
        """
        Tests whether the api nests foreign key value when that is specifically set.
        """
        target = self.CustomerModel.objects.get(age=0)
        previous_customer = self._set_public_access(
            PublicAccessRule(
                row_actions=["read"],
                field_actions={
                    "id": ["read"],
                    "first_name": ["read"],
                    "country": ["read"],
                },
                filters=[ApiFilterRule(field="age", operator=Lookup.EQUALS.value.id, value=target.age)],
            )
        )
        previous_country = self._set_model_public_access(
            self.CountryModel,
            PublicAccessRule(
                row_actions=["read"],
                field_actions={
                    "id": ["read"],
                    "name": ["read"],
                },
            ),
        )
        self.CustomerModel.bloomerp_config.api_settings.nesting = [
            ApiNesting(for_field="country", fields=["name"], on_action=["read"])
        ]

        try:
            request = self.factory.get(f"/api/customers/{target.pk}/")
            view = self.ApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(target.pk))

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["first_name"], target.first_name)
            self.assertEqual(
                response.data["country"],
                {
                    self.CountryModel._meta.pk.name: target.country.pk,
                    "name": target.country.name,
                },
            )
        finally:
            self._restore_public_access(previous_customer)
            self._restore_model_config(self.CountryModel, previous_country)

    def test_api_read_nests_foreign_key_as_dict_when_calling_with_admin_user(self):
        """
        Tests whether a nested foreign key is serialized as a dictionary for
        an authenticated admin user.
        """
        target = self.CustomerModel.objects.get(age=0)
        previous_customer = getattr(self.CustomerModel, "bloomerp_config", None)
        self.CustomerModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                nesting=[
                    ApiNesting(for_field="country", fields=["name"], on_action=["read"])
                ],
            )
        )

        try:
            request = self.factory.get(f"/api/customers/{target.pk}/")
            force_authenticate(request, user=self.admin_user)

            view = self.ApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(target.pk))

            self.assertEqual(response.status_code, 200)
            self.assertIsInstance(response.data["country"], dict)
            self.assertEqual(
                response.data["country"],
                {
                    self.CountryModel._meta.pk.name: target.country.pk,
                    "name": target.country.name,
                },
            )
        finally:
            self._restore_model_config(self.CustomerModel, previous_customer)

    def test_api_read_omits_nested_reverse_relation_when_parent_field_not_publicly_allowed(self):
        """
        This tests whether public access for nesting is ommited when it's not
        specifically set on the model (check field actions for the customer model)

        """
        target = self.CountryModel.objects.get(name="Belgium")
        previous_country = self._set_model_public_access(
            self.CountryModel,
            PublicAccessRule(
                row_actions=["read"],
                field_actions={
                    "id": ["read"],
                    "name": ["read"],
                },
                filters=[ApiFilterRule(field="name", operator=Lookup.EQUALS.value.id, value=target.name)],
            ),
            nesting=[
                ApiNesting(for_field="customer_set", fields=["id", "first_name"], on_action=["read"])
            ],
        )
        previous_customer = self._set_model_public_access(
            self.CustomerModel,
            PublicAccessRule(
                row_actions=["read"],
                field_actions={
                    "id": ["read"],
                    "first_name": ["read"],
                },
            ),
        )

        try:
            request = self.factory.get(f"/api/countries/{target.pk}/")
            view = self.CountryApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(target.pk))

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["name"], target.name)
            self.assertNotIn("customer_set", response.data)
        finally:
            self._restore_model_config(self.CountryModel, previous_country)
            self._restore_model_config(self.CustomerModel, previous_customer)

    def test_api_read_nests_reverse_relation_when_calling_with_admin_user(self):
        """
        This tests whether a user with the correct permission can view the nested fields
        """
        target = self.CountryModel.objects.get(name="Belgium")
        previous_country = getattr(self.CountryModel, "bloomerp_config", None)
        self.CountryModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                nesting=[
                    ApiNesting(
                        for_field="customer_set",
                        fields=["id", "first_name"],
                        on_action=["read"],
                    )
                ],
            )
        )
        try:
            request = self.factory.get(f"/api/countries/{target.pk}/")
            force_authenticate(request, user=self.admin_user)
            view = self.CountryApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(target.pk))

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["name"], target.name)
            self.assertIsInstance(response.data["customer_set"], list)
            self.assertGreater(len(response.data["customer_set"]), 0)
            self.assertTrue(
                all(isinstance(item, dict) for item in response.data["customer_set"])
            )
            self.assertTrue(
                all(set(item.keys()) == {"id", "first_name"} for item in response.data["customer_set"])
            )
        finally:
            self._restore_model_config(self.CountryModel, previous_country)
            
    def test_user_with_partial_permission_can_only_see_specific_nested_fields(self):
        """Tests whether users with partial permission can only see specific nested
        fields.
        """
        target = self.CountryModel.objects.get(name="Belgium")
        previous_country = getattr(self.CountryModel, "bloomerp_config", None)
        self.CountryModel.bloomerp_config = BloomerpModelConfig(
            api_settings=ApiSettings(
                enable_auto_generation=True,
                nesting=[
                    ApiNesting(
                        for_field="customer_set",
                        fields=["id", "first_name", "last_name", "age"],
                        on_action=["read"],
                    )
                ],
            )
        )

        country_content_type = ContentType.objects.get_for_model(self.CountryModel)
        customer_content_type = ContentType.objects.get_for_model(self.CustomerModel)

        customer_set_field, _ = ApplicationField.objects.update_or_create(
            content_type=country_content_type,
            field="customer_set",
            defaults={
                "field_type": "OneToManyField",
                "meta": {
                    "auto_created": True,
                    "related_model": customer_content_type.pk,
                },
                "related_model": customer_content_type,
                "db_column": None,
                "db_table": None,
                "db_field_type": None,
            },
        )

        country_fields = {
            field.field: field for field in ApplicationField.get_for_model(self.CountryModel)
        }
        country_fields["customer_set"] = customer_set_field

        country_field_policy = FieldPolicy.objects.create(
            content_type=country_content_type,
            name="Country nested field policy",
            rule={
                str(country_fields["name"].id): ["view_country"],
                str(country_fields["customer_set"].id): ["view_country"],
            },
        )
        country_row_policy = RowPolicy.objects.create(
            content_type=country_content_type,
            name="Country nested row policy",
        )
        country_row_rule = RowPolicyRule.objects.create(
            row_policy=country_row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(country_fields["name"].id),
                        operator=Lookup.EQUALS.value.id,
                        value=target.name,
                    )
                ]
            ).model_dump(),
        )
        country_row_rule.add_permission("view_country")
        country_policy = Policy.objects.create(
            name="Country nested policy",
            description="Allows viewing Belgium with nested customers.",
            row_policy=country_row_policy,
            field_policy=country_field_policy,
        )

        customer_fields = {
            field.field: field for field in ApplicationField.get_for_model(self.CustomerModel)
        }
        customer_field_policy = FieldPolicy.objects.create(
            content_type=customer_content_type,
            name="Customer nested field policy",
            rule={
                str(customer_fields["first_name"].id): ["view_customer"],
            },
        )
        customer_row_policy = RowPolicy.objects.create(
            content_type=customer_content_type,
            name="Customer nested row policy",
        )
        customer_row_rule = RowPolicyRule.objects.create(
            row_policy=customer_row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(customer_fields["created_by"].id),
                        operator=Lookup.EQUALS_USER.value.id,
                        value="$user",
                    )
                ]
            ).model_dump(),
        )
        customer_row_rule.add_permission("view_customer")
        customer_policy = Policy.objects.create(
            name="Customer nested policy",
            description="Allows viewing owned customer first names only.",
            row_policy=customer_row_policy,
            field_policy=customer_field_policy,
        )

        country_policy.assign_user(self.normal_user)
        customer_policy.assign_user(self.normal_user)

        try:
            request = self.factory.get(f"/api/countries/{target.pk}/")
            force_authenticate(request, user=self.normal_user)

            view = self.CountryApiViewSet.as_view({"get": "retrieve"})
            response = view(request, pk=str(target.pk))

            self.assertEqual(response.status_code, 200)
            self.assertIn("customer_set", response.data)
            self.assertEqual(len(response.data["customer_set"]), 2)
            self.assertEqual(
                {item["first_name"] for item in response.data["customer_set"]},
                {"Jaimy 0", "Jaimy 1"},
            )
            self.assertTrue(
                all(set(item.keys()) == {"first_name"} for item in response.data["customer_set"])
            )
        finally:
            self._restore_model_config(self.CountryModel, previous_country)

    def test_api_list_uses_user_access_for_authenticated_users_without_internal_permissions(self):
        """
        Authenticated users without normal BloomERP permissions should still be able
        to list only their own rows and only the fields granted by a user access rule.
        """
        previous = self._set_user_access(
            UserAccessRule(
                through_field="created_by",
                field_actions={
                    "id": ["view"],
                    "first_name": ["view"],
                },
                row_actions=["view"],
            )
        )

        try:
            # 1. Call the auto-generated list endpoint as a normal authenticated user.
            request = self.factory.get("/api/customers/")
            force_authenticate(request, user=self.normal_user)

            view = self.ApiViewSet.as_view({"get": "list"})
            response = view(request)

            # 2. Confirm only owned rows are returned.
            self.assertEqual(response.status_code, 200)
            results = self._extract_results(response)
            self.assertEqual(len(results), 2)
            self.assertEqual({row["first_name"] for row in results}, {"Jaimy 0", "Jaimy 1"})

            # 3. Confirm only the allowed fields are exposed.
            self.assertTrue(all("first_name" in row for row in results))
            self.assertTrue(all("last_name" not in row for row in results))
            self.assertTrue(all("age" not in row for row in results))
        finally:
            self._restore_public_access(previous)

    def test_api_list_user_access_filters_narrow_results_within_through_field_scope(self):
        """
        Authenticated users without normal BloomERP permissions should have their
        user access results filtered first by the through field and then further
        narrowed by any extra user access filters.
        """
        previous = self._set_user_access(
            UserAccessRule(
                through_field="created_by",
                field_actions={
                    "id": ["view"],
                    "first_name": ["view"],
                },
                row_actions=["view"],
                filters=[ApiFilterRule(field="first_name", operator=Lookup.NOT_EQUALS.value.id, value="Jaimy 0")],
            )
        )

        try:
            # 1. Call the auto-generated list endpoint as a normal authenticated user.
            request = self.factory.get("/api/customers/")
            force_authenticate(request, user=self.normal_user)

            view = self.ApiViewSet.as_view({"get": "list"})
            response = view(request)

            # 2. Confirm the through field limits results to owned rows first.
            self.assertEqual(response.status_code, 200)
            results = self._extract_results(response)

            # 3. Confirm the extra filter removes the excluded owned record.
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["first_name"], "Jaimy 1")
            self.assertNotIn("last_name", results[0])
            self.assertNotIn("age", results[0])
        finally:
            self._restore_public_access(previous)

    def test_api_create_uses_user_access_for_authenticated_users_without_internal_permissions(self):
        """
        Authenticated users without normal BloomERP permissions should be able to
        create objects through the auto-generated API when the submitted values
        satisfy a user access rule's ownership and filter constraints.
        """
        previous = self._set_user_access(
            UserAccessRule(
                through_field="created_by",
                field_actions={
                    "first_name": ["add", "view"],
                    "last_name": ["add", "view"],
                    "age": ["add"],
                    "country": ["add", "view"],
                    "created_by": ["add"],
                },
                row_actions=["add", "view"],
                filters=[ApiFilterRule(field="age", operator=Lookup.GREATER_THAN_OR_EQUAL.value.id, value=18)],
            )
        )

        try:
            # 1. Submit a create request that matches the user access rule.
            request = self.factory.post(
                "/api/customers/",
                {
                    "first_name": "Owned",
                    "last_name": "Record",
                    "age": 21,
                    "country": self.CountryModel.objects.get(name="Belgium").pk,
                    "created_by": self.normal_user.pk,
                },
                format="json",
            )
            force_authenticate(request, user=self.normal_user)

            view = self.ApiViewSet.as_view({"post": "create"})
            response = view(request)

            # 2. Confirm the object is created.
            self.assertEqual(response.status_code, 201)
            created = self.CustomerModel.objects.get(first_name="Owned")
            self.assertEqual(created.created_by, self.normal_user)
            self.assertEqual(created.age, 21)

            # 3. Confirm add-time field filtering still applies to the response.
            self.assertIn("first_name", response.data)
            self.assertIn("last_name", response.data)
            self.assertIn("age", response.data)
            self.assertIn("country", response.data)
            self.assertIn("created_by", response.data)
        finally:
            self._restore_public_access(previous)

    def test_api_update_rejects_user_access_changes_that_move_object_outside_scope(self):
        """
        Authenticated users without normal BloomERP permissions should not be able
        to update an object in a way that breaks the user access rule that granted
        access in the first place.
        """
        target = self.CustomerModel.objects.get(age=0)
        previous = self._set_user_access(
            UserAccessRule(
                through_field="created_by",
                field_actions={
                    "created_by": ["change"],
                    "first_name": ["change", "view"],
                },
                row_actions=["view", "change"],
            )
        )

        try:
            # 1. Attempt to move an owned object outside the user's ownership scope.
            request = self.factory.patch(
                f"/api/customers/{target.pk}/",
                {"created_by": self.admin_user.pk},
                format="json",
            )
            force_authenticate(request, user=self.normal_user)

            view = self.ApiViewSet.as_view({"patch": "partial_update"})
            response = view(request, pk=str(target.pk))

            # 2. Confirm the update is rejected.
            self.assertEqual(response.status_code, 403)

            # 3. Confirm the object remains unchanged.
            target.refresh_from_db()
            self.assertEqual(target.created_by, self.normal_user)
        finally:
            self._restore_public_access(previous)

    def test_api_user_access_supports_self_through_field_for_user_model(self):
        """
        User access rules that scope the User model via the Self wildcard should
        only grant access to the authenticated user's own record.
        """
        previous = self._set_model_user_access(
            User,
            UserAccessRule(
                through_field="Self",
                field_actions={
                    "email": ["view", "change"],
                },
                row_actions=["view", "change"],
            ),
        )

        user_viewset = generate_model_viewset_class(
            model=User,
            serializer=generate_serializer(User),
            base_viewset=BloomerpModelViewSet,
        )

        try:
            # 1. Update the authenticated user through a Self-scoped user access rule.
            request = self.factory.patch(
                f"/api/users/{self.normal_user.pk}/",
                {"email": "updated@example.com"},
                format="json",
            )
            force_authenticate(request, user=self.normal_user)

            view = user_viewset.as_view({"patch": "partial_update"})
            response = view(request, pk=str(self.normal_user.pk))

            # 2. Confirm the request succeeds for the authenticated user's own record.
            self.assertEqual(response.status_code, 200)

            # 3. Confirm the requested change is persisted.
            self.normal_user.refresh_from_db()
            self.assertEqual(self.normal_user.email, "updated@example.com")
        finally:
            self._restore_model_config(User, previous)
    
    # --------------------------------------
    # Global permissions
    # --------------------------------------
    def test_admin_has_global_permission(self):
        manager = UserPermissionManager(self.admin_user)

        self.assertTrue(manager.has_global_permission(self.CustomerModel, "add_customer"))

    def test_normal_user_has_no_global_permission_without_legacy_or_policy_access(self):
        manager = UserPermissionManager(self.normal_user)

        self.assertFalse(manager.has_global_permission(self.CustomerModel, "add_customer"))

    def test_normal_user_has_global_permission_via_legacy_django_permissions(self):
        permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            codename="add_customer",
        )
        self.normal_user.user_permissions.add(permission)

        manager = UserPermissionManager(self.normal_user)

        self.assertTrue(manager.has_global_permission(self.CustomerModel, "add_customer"))

    def test_normal_user_has_global_permission_via_policy_global_permissions(self):
        permission = Permission.objects.get(
            content_type=ContentType.objects.get_for_model(self.CustomerModel),
            codename="add_customer",
        )
        self.policy.assign_user(self.normal_user)
        self.policy.global_permissions.add(permission)

        manager = UserPermissionManager(self.normal_user)

        self.assertTrue(manager.has_global_permission(self.CustomerModel, "add_customer"))
    

    # ---------------------------------------
    # Assign creator permission tests
    # ---------------------------------------
    def test_assign_creator_permission(self):
        """
        This test tests whether the assign creator permission allows the user to actually view the objects 
        that he or she has created.
        """
        # 1. Create a object
        obj = self.CustomerModel.objects.create(
            first_name="Creator",
            last_name="Person",
            age=30,
            country=self.CountryModel.objects.first(),
            created_by=self.normal_user
        )

        other_obj = self.CustomerModel.objects.create(
            first_name="Other",
            last_name="Person",
            age=30,
            country=self.CountryModel.objects.first(),
            created_by=self.admin_user
        )

        # 2. Assign the creator permission
        manager = UserPermissionManager(self.normal_user)
        manager.assign_creator_permission(
            self.CustomerModel,
            field_policy={"__all__": "__all__"},
            row_permissions="__all__"
        )
        
        # 3. Check if the user has access to the object
        for perm in self.CustomerModel._meta.default_permissions:
            self.assertTrue(manager.has_access_to_object(obj, perm))

        for perm in self.CustomerModel._meta.default_permissions:
            self.assertFalse(manager.has_access_to_object(other_obj, perm))

    def test_assign_creator_permission_can_add_field_without_change_permission(self):
        """
        This test tests whether assign creator permission can allow a field
        on create without also allowing that field on change.
        """
        # 1. Create an owned object
        obj = self.CustomerModel.objects.create(
            first_name="Creator",
            last_name="Person",
            age=30,
            country=self.CountryModel.objects.first(),
            created_by=self.normal_user
        )

        # 2. Assign add access to age, but no change access to age
        manager = UserPermissionManager(self.normal_user)
        manager.assign_creator_permission(
            self.CustomerModel,
            field_policy={
                "first_name": ["add", "view", "change"],
                "last_name": ["add", "view", "change"],
                "country": ["add", "view", "change"],
                "age": ["add", "view"],
            },
            row_permissions=["add", "view", "change"]
        )

        # 3. Check if the field can be used on add
        self.assertTrue(manager.has_field_permission(self.age_field, "add_customer"))

        # 4. Check if the same field cannot be changed later
        self.assertFalse(manager.has_field_permission(self.age_field, "change_customer"))

        # 5. Check if the user still has row-level change access to the object
        self.assertTrue(manager.has_access_to_object(obj, "change"))

        # 6. Check if another field can still be changed
        self.assertTrue(manager.has_field_permission(self.first_name_field, "change_customer"))

    def test_assign_creator_permission_reuses_existing_policy(self):
        """
        This test tests whether assign creator permission reuses the existing
        creator policy instead of creating duplicates.
        """
        # 1. Construct the manager
        manager = UserPermissionManager(self.normal_user)

        # 2. Assign the creator permission twice
        manager.assign_creator_permission(
            self.CustomerModel,
            field_policy={
                "first_name": ["view"],
            },
            row_permissions=["view"]
        )
        manager.assign_creator_permission(
            self.CustomerModel,
            field_policy={
                "first_name": ["change"],
            },
            row_permissions=["change"]
        )

        # 3. Get the policies assigned to the user for this model
        policies = manager.get_user_policies().filter(
            row_policy__content_type=ContentType.objects.get_for_model(self.CustomerModel),
            name__startswith="Creator policy "
        )

        # 4. Check that there is only one creator policy
        self.assertEqual(policies.count(), 1)

        # 5. Check that the creator rule only exists once
        creator_policy = policies.first()
        self.assertEqual(creator_policy.row_policy.rules.count(), 1)

        # 6. Check that permissions from both calls are applied
        self.assertTrue(manager.has_field_permission(self.first_name_field, "view_customer"))
        self.assertTrue(manager.has_field_permission(self.first_name_field, "change_customer"))


    

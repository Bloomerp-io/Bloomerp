from bloomerp.lookups import builtins as lookups
from bloomerp.models.application_field import ApplicationField
from bloomerp.permissions.definition import (
    AccessRule,
    BloomerpPermission,
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.permissions.manager import (
    PolicyManager,
    UserPolicyManager,
    field_access_annotation_name,
)
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from django.contrib.contenttypes.models import ContentType
from django.db import models

from bloomerp.tests.utils.names import FIRST_NAMES
"""
Superuser, anonymous user, and user with no policies.
Direct-user and group policies.
Global versus row-level grants.
Two policies granting different fields for different rows.
Multiple permissions with ANY versus ALL.
Wildcard rules.
Invalid fields, operators, and content-type combinations.
Create-candidate versus stored-object evaluation.
Batch field resolution and query counts.
Compatibility between the old and new manager APIs.
"""

class TestUserPermissionManager(BaseBloomerpTestCaseWithModels):
    """
    Test cases for UserPermissionManager
    """
    auto_create_customers = True
    auto_create_users = True
    use_bloomerp_base = True
    create_foreign_models = True

    def extendedSetup(self):
        """
        Extended setup for UserPermissionManager tests
        """
    
    def _validate_queryset_results(self, input_queryset: models.QuerySet, expected_queryset: models.QuerySet):
        """
        Validates that the input queryset matches the expected queryset.

        Args:
            input_queryset (models.QuerySet): The queryset to validate.
            expected_queryset (models.QuerySet): The expected queryset to compare against.
        """
        self.assertQuerySetEqual(
            input_queryset.order_by('id'),
            expected_queryset.order_by('id'),
            transform=lambda x: x
        )
    
    
    # --------------------------------
    # ROW ACCESS TESTS
    # --------------------------------
    # --------------------------------
    # NO POLICIES TESTS
    # --------------------------------
    def test_admin_user_has_access_to_all_objects(self):
        """
        UC: An admin should always have access to all objects
        Expected Result: admin has access to all objects
        """
        #1. Query objects for admin
        manager = UserPolicyManager(self.admin_user)
        
        #2. Check access to all objects
        for obj in self.CustomerModel.objects.all():
            self.assertTrue(manager.has_access_to_object(obj, BloomerpPermission.VIEW), f"Admin should have access to {obj}")
            
        #3. Check accessible queryset
        accessible_queryset = manager.get_accessible_queryset(self.CustomerModel, BloomerpPermission.VIEW)
        
        self._validate_queryset_results(accessible_queryset, self.CustomerModel.objects.all())
    
    def test_normal_user_with_no_policies_has_no_access(self):
        """
        UC: A normal user with no policies should have no access to any objects
        
        Expected Result: normal user has no access to any objects
        """
        #1. Query objects for normal user
        manager = UserPolicyManager(self.normal_user)
        
        #2. Check access to all objects
        for obj in self.CustomerModel.objects.all():
            self.assertFalse(manager.has_access_to_object(obj, BloomerpPermission.VIEW), f"Normal user should not have access to {obj}")
            
        #3. Check accessible queryset
        accessible_queryset = manager.get_accessible_queryset(self.CustomerModel, BloomerpPermission.VIEW)
        
        #4. Validate that the accessible queryset is empty
        self._validate_queryset_results(accessible_queryset, self.CustomerModel.objects.none())

    def test_supplied_access_rules_can_preview_without_a_stored_policy(self):
        first_name = FIRST_NAMES[0]
        access_rule = AccessRule(
            row_permissions=[
                RowPolicyRuleContent(
                    permissions=["preview"],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="first_name",
                            operator=lookups.EQUALS.id,
                            value=first_name,
                        )
                    ],
                )
            ]
        )

        queryset = UserPolicyManager(self.normal_user).get_queryset_for_access_rules(
            self.CustomerModel,
            [access_rule],
            "preview",
        )

        self._validate_queryset_results(
            queryset,
            self.CustomerModel.objects.filter(first_name=first_name),
        )
        
    def test_normal_user_with_only_global_access_has_no_access_to_objects(self):
        """
        UC: A normal user with only global access should have no access to any objects
        
        Expected Result: normal user has no access to any objects
        """
        PERM = BloomerpPermission.VIEW
        
        #1. Create a global policy for the normal user
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[],
            global_permissions=[PERM],
        )
        PolicyManager.assign(policy, self.normal_user)
        
        #2. Query objects for normal user
        manager = UserPolicyManager(self.normal_user)
        
        #3. Check access to all objects
        self._validate_queryset_results(
            manager.get_accessible_queryset(self.CustomerModel, PERM),
            self.CustomerModel.objects.none()
        )

    def test_accessible_content_types_require_global_permission_with_row_grant(self):
        """A row grant alone must not make a model available to data-view configuration."""
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="first_name",
                            operator=lookups.EQUALS.id,
                            value=FIRST_NAMES[0],
                        )
                    ],
                )
            ],
            global_permissions=[BloomerpPermission.VIEW],
        )
        policy.global_permissions.clear()
        PolicyManager.assign(policy, self.normal_user)

        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        manager = UserPolicyManager(self.normal_user)

        self.assertFalse(
            manager.get_accessible_content_types(BloomerpPermission.VIEW)
            .filter(pk=content_type.pk)
            .exists()
        )

        policy.global_permissions.add(
            *policy.row_policy.content_type.permission_set.filter(codename="view_customer")
        )
        manager = UserPolicyManager(self.normal_user)

        self.assertTrue(
            manager.get_accessible_content_types(BloomerpPermission.VIEW)
            .filter(pk=content_type.pk)
            .exists()
        )
        
    # --------------------------------
    # ROW ACCESS TESTS
    # --------------------------------
    # --------------------------------
    # HAS POLICIES TESTS
    # --------------------------------
    
    # EQUAL OPERATOR
    def test_normal_user_with_single_row_policy_has_access_to_objects_operator_EQUALS(self):
        """
        UC: A normal user with a single row-level policy should have access to specific objects
        
        Expected Result: normal user has access to specific objects defined by the policy
        """
        first_name_value = FIRST_NAMES[0]
        
        #1. Create the policy
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="first_name",
                            operator=lookups.EQUALS.id,
                            value=first_name_value
                        )
                    ]
                )
            ],
            global_permissions=[BloomerpPermission.VIEW],
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 2. Query objects for normal user
        manager = UserPolicyManager(self.normal_user)
        
        # 3. Check access to specific objects
        self._validate_queryset_results(
            manager.get_accessible_queryset(self.CustomerModel, BloomerpPermission.VIEW),
            self.CustomerModel.objects.filter(first_name=first_name_value)
        )
    
    # DOES NOT EQUAL OPERATOR
    def test_normal_user_with_single_row_policy_has_access_to_objects_operator_DOES_NOT_EQUAL(self):
        """
        UC: A normal user with a single row-level policy should have access to specific objects
        
        Expected Result: normal user has access to specific objects defined by the policy
        """
        first_name_value = FIRST_NAMES[0]
        
        #1. Create the policy
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="first_name",
                            operator=lookups.NOT_EQUALS.id,
                            value=first_name_value
                        )
                    ]
                )
            ],
            global_permissions=[BloomerpPermission.VIEW],
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 2. Query objects for normal user
        manager = UserPolicyManager(self.normal_user)
        
        # 3. Check access to specific objects
        self._validate_queryset_results(
            manager.get_accessible_queryset(self.CustomerModel, BloomerpPermission.VIEW),
            self.CustomerModel.objects.exclude(first_name=first_name_value)
        )

    def test_candidate_matching_uses_in_memory_state_without_persisting_it(self):
        current = self.CustomerModel.objects.exclude(first_name=FIRST_NAMES[0]).first()
        original_name = current.first_name
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.CHANGE],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="first_name",
                            operator=lookups.EQUALS.id,
                            value=FIRST_NAMES[0],
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)
        manager = UserPolicyManager(self.normal_user)
        candidate = self.CustomerModel.objects.get(pk=current.pk)

        self.assertFalse(
            manager.candidate_matches_row_policies(
                candidate,
                BloomerpPermission.CHANGE,
            )
        )
        candidate.first_name = FIRST_NAMES[0]
        self.assertTrue(
            manager.candidate_matches_row_policies(
                candidate,
                BloomerpPermission.CHANGE,
            )
        )
        current.refresh_from_db()
        self.assertEqual(current.first_name, original_name)

    def test_candidate_matching_supports_nested_relations(self):
        country_field = ApplicationField.get_for_model(self.CustomerModel).get(
            field="country"
        )
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.ADD],
                    conditions=[
                        RowPolicyRuleCondition(
                            application_field_id=str(country_field.pk),
                            operator="__country__planet__name",
                            value="Earth",
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)
        manager = UserPolicyManager(self.normal_user)

        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel(
                    country=self.CountryModel.objects.get(name="Belgium")
                ),
                BloomerpPermission.ADD,
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel(
                    country=self.CountryModel.objects.get(name="Helvetia")
                ),
                BloomerpPermission.ADD,
            )
        )

    def test_related_user_rule_filters_queryset_and_matches_candidate(self):
        country_field = ApplicationField.get_for_model(self.CustomerModel).get(
            field="country"
        )
        allowed_country = self.CountryModel.objects.get(name="Belgium")
        blocked_country = self.CountryModel.objects.get(name="Helvetia")
        allowed_country.created_by = self.normal_user
        allowed_country.save(update_fields=["created_by"])
        blocked_country.created_by = self.admin_user
        blocked_country.save(update_fields=["created_by"])
        allowed_customer = self.CustomerModel.objects.create(
            first_name="Allowed",
            last_name="Employee",
            age=30,
            country=allowed_country,
        )
        blocked_customer = self.CustomerModel.objects.create(
            first_name="Blocked",
            last_name="Employee",
            age=30,
            country=blocked_country,
        )
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            application_field_id=str(country_field.pk),
                            field="country__created_by",
                            operator=lookups.EQUALS_USER.id,
                            value="$user",
                        )
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)
        manager = UserPolicyManager(self.normal_user)

        accessible = manager.get_accessible_queryset(
            self.CustomerModel,
            BloomerpPermission.VIEW,
        )

        self.assertIn(allowed_customer, accessible)
        self.assertNotIn(blocked_customer, accessible)
        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel(country=allowed_country),
                BloomerpPermission.VIEW,
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel(country=blocked_country),
                BloomerpPermission.VIEW,
            )
        )

    def test_candidate_matching_supports_user_and_typed_comparisons(self):
        created_by = ApplicationField.get_for_model(self.CustomerModel).get(
            field="created_by"
        )
        age = ApplicationField.get_for_model(self.CustomerModel).get(field="age")
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={},
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.ADD],
                    conditions=[
                        RowPolicyRuleCondition(
                            application_field_id=str(created_by.pk),
                            operator=lookups.EQUALS_USER.id,
                            value="$user",
                        ),
                        RowPolicyRuleCondition(
                            application_field_id=str(age.pk),
                            operator=lookups.GREATER_THAN_OR_EQUAL.id,
                            value="18",
                        ),
                    ],
                )
            ],
        )
        PolicyManager.assign(policy, self.normal_user)
        manager = UserPolicyManager(self.normal_user)

        self.assertTrue(
            manager.candidate_matches_row_policies(
                self.CustomerModel(age=18, created_by=self.normal_user),
                BloomerpPermission.ADD,
            )
        )
        self.assertFalse(
            manager.candidate_matches_row_policies(
                self.CustomerModel(age=17, created_by=self.normal_user),
                BloomerpPermission.ADD,
            )
        )

    # D
    def test_row_rules_from_different_policies_are_combined_with_or(self):
        """
        UC: A normal user with multiple row-level policies should have access to objects matching any policy
        
        Expected Result: normal user has access to objects matching either row-level policy
        """
        first_value, second_value = FIRST_NAMES[:2]
        
        #1. Create two policies for different first-name values
        for value in (first_value, second_value):
            policy = PolicyManager.create_policy(
                model_or_content_type=self.CustomerModel,
                field_permissions={},
                row_permissions=[
                    RowPolicyRuleContent(
                        connector="AND",
                        permissions=[BloomerpPermission.VIEW],
                        conditions=[
                            RowPolicyRuleCondition(
                                field="first_name",
                                operator=lookups.EQUALS.id,
                                value=value,
                            )
                        ],
                    )
                ],
                global_permissions=[BloomerpPermission.VIEW],
            )
            PolicyManager.assign(policy, self.normal_user)

        #2. Query objects for normal user
        manager = UserPolicyManager(self.normal_user)

        #3. Check access to objects matching either policy
        self._validate_queryset_results(
            manager.get_accessible_queryset(
                self.CustomerModel,
                BloomerpPermission.VIEW,
            ),
            self.CustomerModel.objects.filter(
                first_name__in=[first_value, second_value]
            ),
        )
    
    
    # --------------------------------
    # FIELD ACCESS TESTS
    # --------------------------------
    # --------------------------------
    # NO POLICIES TESTS
    # --------------------------------
    def test_admin_user_has_access_to_all_fields(self):
        """
        UC: An admin should always have access to all fields
        
        Expected Result: admin has access to all fields
        """
        #1. Query fields for admin
        manager = UserPolicyManager(self.admin_user)
        
        #2. Check access to all fields
        fields = manager.get_accessible_fields(self.CustomerModel, BloomerpPermission.VIEW)
        
        #3. Validate that the fields match the model's fields
        self._validate_queryset_results(fields, ApplicationField.get_for_model(self.CustomerModel))
    
    def test_normal_user_with_no_policies_has_no_access_to_fields(self):
        """
        UC: A normal user with no policies should have no access to any fields
        
        Expected Result: normal user has no access to any fields
        """
        #1. Query fields for normal user
        manager = UserPolicyManager(self.normal_user)
        
        #2. Check access to all fields
        fields = manager.get_accessible_fields(self.CustomerModel, BloomerpPermission.VIEW)
        
        #3. Validate that the fields queryset is empty
        self._validate_queryset_results(fields, ApplicationField.objects.none())
    
    # --------------------------------
    # FIELD ACCESS TESTS
    # --------------------------------
    # --------------------------------
    # HAS POLICIES TESTS
    # --------------------------------
    def test_normal_user_with_single_field_policy_has_access_to_fields(self):
        """
        UC: A normal user with a single field-level policy should have access to specific fields
        
        Expected Result: normal user has access to specific fields defined by the policy
        """
        #1. Create the policy
        policy = PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={
                "first_name": [BloomerpPermission.VIEW],
            },
            row_permissions=[],
        )
        PolicyManager.assign(policy, self.normal_user)
        
        # 2. Query fields for normal user
        manager = UserPolicyManager(self.normal_user)
        
        # 3. Check access to specific fields
        self._validate_queryset_results(
            manager.get_accessible_fields(self.CustomerModel, BloomerpPermission.VIEW),
            ApplicationField.get_for_model(self.CustomerModel).filter(field="first_name")
        )

    def test_field_permissions_are_scoped_to_the_matching_rows(self):
        """
        UC: A normal user with different field permissions for different rows should only access the fields granted for each row
        
        Expected Result: each object exposes only the fields granted by the row policy matching that object
        """
        first_value, second_value = FIRST_NAMES[:2]
        grants = (
            (first_value, "first_name"),
            (second_value, "last_name"),
        )
        
        #1. Create policies granting different fields for different rows
        for row_value, field_name in grants:
            policy = PolicyManager.create_policy(
                model_or_content_type=self.CustomerModel,
                field_permissions={
                    field_name: [BloomerpPermission.VIEW],
                },
                row_permissions=[
                    RowPolicyRuleContent(
                        connector="AND",
                        permissions=[BloomerpPermission.VIEW],
                        conditions=[
                            RowPolicyRuleCondition(
                                field="first_name",
                                operator=lookups.EQUALS.id,
                                value=row_value,
                            )
                        ],
                    )
                ],
            )
            PolicyManager.assign(policy, self.normal_user)

        #2. Query objects for normal user
        manager = UserPolicyManager(self.normal_user)
        first_object = self.CustomerModel.objects.filter(
            first_name=first_value
        ).first()
        second_object = self.CustomerModel.objects.filter(
            first_name=second_value
        ).first()

        #3. Check that the first object only exposes the first-name field
        self._validate_queryset_results(
            manager.get_accessible_fields_for_object(
                first_object,
                BloomerpPermission.VIEW,
            ),
            ApplicationField.get_for_model(self.CustomerModel).filter(
                field="first_name"
            ),
        )
        
        #4. Check that the second object only exposes the last-name field
        self._validate_queryset_results(
            manager.get_accessible_fields_for_object(
                second_object,
                BloomerpPermission.VIEW,
            ),
            ApplicationField.get_for_model(self.CustomerModel).filter(
                field="last_name"
            ),
        )

    def test_field_permissions_can_be_resolved_for_a_queryset_in_one_query(self):
        """Per-row field grants are attached to a batch, not queried per object."""
        first_value, second_value = FIRST_NAMES[:2]
        fields = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
            if field.field in {"first_name", "last_name"}
        }

        for row_value, field_name in (
            (first_value, "first_name"),
            (second_value, "last_name"),
        ):
            PolicyManager.assign(
                PolicyManager.create_policy(
                    model_or_content_type=self.CustomerModel,
                    field_permissions={field_name: [BloomerpPermission.VIEW]},
                    row_permissions=[
                        RowPolicyRuleContent(
                            connector="AND",
                            permissions=[BloomerpPermission.VIEW],
                            conditions=[
                                RowPolicyRuleCondition(
                                    field="first_name",
                                    operator=lookups.EQUALS.id,
                                    value=row_value,
                                )
                            ],
                        )
                    ],
                ),
                self.normal_user,
            )

        manager = UserPolicyManager(self.normal_user)
        queryset = manager.annotate_field_permissions(
            manager.get_queryset(self.CustomerModel, BloomerpPermission.VIEW),
            [fields["first_name"], fields["last_name"]],
            BloomerpPermission.VIEW,
        ).order_by("first_name")

        with self.assertNumQueries(1):
            objects = list(queryset)

        self.assertEqual([obj.first_name for obj in objects], [first_value, second_value])
        self.assertTrue(
            getattr(objects[0], field_access_annotation_name(fields["first_name"]))
        )
        self.assertFalse(
            getattr(objects[0], field_access_annotation_name(fields["last_name"]))
        )
        self.assertFalse(
            getattr(objects[1], field_access_annotation_name(fields["first_name"]))
        )
        self.assertTrue(
            getattr(objects[1], field_access_annotation_name(fields["last_name"]))
        )

    
    # --------------------------------
    # SQL
    # --------------------------------    
    def test_normal_user_gets_accessible_fields_for_table(self):
        """
        UC: Users want to know which fields they are able to access for a specific table

        Expected Result: The fields the user has access to
        """

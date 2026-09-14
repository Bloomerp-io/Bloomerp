from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from bloomerp.lookups import builtins as lookups
from bloomerp.models import ApplicationField
from bloomerp.models.access_control.field_policy import FieldPolicy
from bloomerp.models.access_control.policy import Policy
from bloomerp.models.access_control.row_policy import RowPolicy
from bloomerp.models.access_control.row_policy_rule import RowPolicyRule
from bloomerp.permissions.definition import BloomerpPermission, RowPolicyRuleCondition, RowPolicyRuleContent
from bloomerp.permissions.manager import PolicyManager
from bloomerp.permissions.manager import ensure_model_permissions
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels

class TestPolicyManager(BaseBloomerpTestCaseWithModels):
    """
    Test cases for PolicyManager
    """
    auto_create_customers = True
    auto_create_users = True
    use_bloomerp_base = True
    create_foreign_models = True

    def extendedSetup(self):
        """
        Extended setup for PolicyManager tests
        """
        ensure_model_permissions(self.CustomerModel)
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.first_name_field = ApplicationField.objects.get(
            content_type=self.content_type,
            field="first_name",
        )
        self.last_name_field = ApplicationField.objects.get(
            content_type=self.content_type,
            field="last_name",
        )

    def create_policy(self) -> Policy:
        return PolicyManager.create_policy(
            model_or_content_type=self.CustomerModel,
            field_permissions={
                "first_name": [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
                "last_name": [BloomerpPermission.VIEW],
            },
            row_permissions=[
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.VIEW],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="first_name",
                            operator=lookups.EQUALS.id,
                            value="John",
                        )
                    ],
                )
            ],
        )
    
    def test_create_policy(self):
        """
        UC: I want to use the PolicyManager as a simplified interface to create policies for models and objects.
        Given a model or object, I want to create a policy with specific permissions and criteria.
        
        Expected Result: The policy is created successfully, and the permissions are applied to the model or object as specified.
        """
        #1. Create a policy for a model with specific permissions and criteria
        policy = self.create_policy()

        # 2. Check that the policy exists with the correct rules
        self.assertEqual(Policy.objects.count(), 1)
        self.assertEqual(RowPolicy.objects.count(), 1)
        self.assertEqual(FieldPolicy.objects.count(), 1)
        self.assertEqual(RowPolicyRule.objects.count(), 1)
        self.assertEqual(policy.row_policy.content_type, self.content_type)
        self.assertEqual(policy.field_policy.content_type, self.content_type)

        # 3. Check that the policy has the correct global permissions
        self.assertEqual(
            set(policy.global_permissions.values_list("codename", flat=True)),
            {"view_customer", "change_customer"},
        )

        # 4. Check that the policy has the correct row permissions
        row_rule = policy.row_policy.rules.get()
        self.assertNotIn("permissions", row_rule.rule)
        self.assertEqual(
            set(row_rule.permissions.values_list("codename", flat=True)),
            {"view_customer"},
        )
        stored_rule = RowPolicyRuleContent.model_validate(row_rule.rule)
        self.assertEqual(stored_rule.connector, "AND")
        self.assertEqual(len(stored_rule.conditions), 1)
        self.assertEqual(stored_rule.conditions[0].field_path, "first_name")
        self.assertEqual(stored_rule.conditions[0].lookup_id, lookups.EQUALS.id)
        self.assertEqual(stored_rule.conditions[0].value, "John")

        # 5. Check that field names were resolved to ApplicationField IDs
        self.assertEqual(
            policy.field_policy.rule,
            {
                str(self.first_name_field.pk): ["view_customer", "change_customer"],
                str(self.last_name_field.pk): ["view_customer"],
            },
        )
        
    def test_assign_user_to_policy(self):
        """
        UC: I want to use the policy manager to assign users to certain policies
        
        Expected Result: user is assigned to policy
        """
        
        #1. Create a policy for a model with specific permissions and criteria
        policy = self.create_policy()
        
        # 2. Assign the normal user to the policy
        PolicyManager.assign(policy, self.normal_user)
        
        # 3. Check that the user is assigned to the policy
        self.assertIn(self.normal_user, policy.users.all())
        
    def test_users_assigned_to_policy(self):
        """
        UC: I want to use the policy manager to get all users assigned to a certain policy
        
        Expected Result: returns all users assigned to the policy
        """
        
        #1. Create a policy for a model with specific permissions and criteria
        policy = self.create_policy()
        
        # 2. Assign the normal user to the policy
        PolicyManager.assign(policy, self.normal_user)
        group = Group.objects.create(name="Policy members")
        self.admin_user.groups.add(group)
        PolicyManager.assign(policy, group)
        
        # 3. Get all users assigned to the policy
        users_assigned = PolicyManager.users_assigned_to_policy(policy)
        
        # 4. Check that the normal user is in the list of users assigned to the policy
        self.assertEqual(
            set(users_assigned),
            {self.normal_user, self.admin_user},
        )
        
    def test_assign_group_to_policy(self):
        """
        UC: I want to use the policy manager to assign groups to certain policies
        
        Expected Result: group is assigned to policy
        """
        
        #1. Create a policy for a model with specific permissions and criteria
        policy = self.create_policy()
        
        # 2. Create a group and assign the normal user to the group
        group = Group.objects.create(name="Test Group")
        self.normal_user.groups.add(group)
        
        # 3. Assign the group to the policy
        PolicyManager.assign(policy, group)
        
        # 4. Check that the group is assigned to the policy
        self.assertIn(group, policy.groups.all())

    def test_create_policy_rolls_back_for_unknown_row_field(self):
        with self.assertRaisesMessage(ValueError, "Unknown field 'does_not_exist'"):
            PolicyManager.create_policy(
                model_or_content_type=self.CustomerModel,
                field_permissions={
                    "first_name": [BloomerpPermission.VIEW],
                },
                row_permissions=[
                    RowPolicyRuleContent(
                        connector="AND",
                        permissions=[BloomerpPermission.VIEW],
                        conditions=[
                            RowPolicyRuleCondition(
                                field="does_not_exist",
                                operator=lookups.EQUALS.id,
                                value="John",
                            )
                        ],
                    )
                ],
            )

        self.assertFalse(Policy.objects.exists())
        self.assertFalse(RowPolicy.objects.exists())
        self.assertFalse(FieldPolicy.objects.exists())

    def test_explicit_global_permissions_must_include_field_permissions(self):
        with self.assertRaisesMessage(
            ValueError,
            "Row and field permissions must also be global permissions: change_customer",
        ):
            PolicyManager.create_policy(
                model_or_content_type=self.CustomerModel,
                field_permissions={
                    "first_name": [BloomerpPermission.VIEW, BloomerpPermission.CHANGE],
                },
                row_permissions=[],
                global_permissions=[BloomerpPermission.VIEW],
            )

        self.assertFalse(Policy.objects.exists())

    def test_create_policy_accepts_model_instance(self):
        customer = self.CustomerModel.objects.first()

        policy = PolicyManager.create_policy(
            model_or_content_type=customer,
            field_permissions={},
            row_permissions=[],
            global_permissions=BloomerpPermission.VIEW,
        )

        self.assertEqual(policy.row_policy.content_type, self.content_type)
        self.assertEqual(policy.field_policy.content_type, self.content_type)

    def test_create_policy_preserves_permissions_per_row_rule(self):
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
                            value="John",
                        )
                    ],
                ),
                RowPolicyRuleContent(
                    connector="AND",
                    permissions=[BloomerpPermission.CHANGE],
                    conditions=[
                        RowPolicyRuleCondition(
                            field="last_name",
                            operator=lookups.EQUALS.id,
                            value="Doe",
                        )
                    ],
                ),
            ],
        )

        rules = list(policy.row_policy.rules.order_by("pk"))
        self.assertEqual(
            list(rules[0].permissions.values_list("codename", flat=True)),
            ["view_customer"],
        )
        self.assertEqual(
            list(rules[1].permissions.values_list("codename", flat=True)),
            ["change_customer"],
        )
        self.assertEqual(
            set(policy.global_permissions.values_list("codename", flat=True)),
            {"view_customer", "change_customer"},
        )

    def test_create_policy_requires_permissions_on_each_row_rule(self):
        with self.assertRaisesMessage(
            ValueError,
            "Each row policy rule requires at least one permission",
        ):
            PolicyManager.create_policy(
                model_or_content_type=self.CustomerModel,
                field_permissions={"first_name": [BloomerpPermission.VIEW]},
                row_permissions=[
                    RowPolicyRuleContent(
                        connector="AND",
                        conditions=[
                            RowPolicyRuleCondition(
                                field="first_name",
                                operator=lookups.EQUALS.id,
                                value="John",
                            )
                        ],
                    )
                ],
            )

    def test_explicit_global_permissions_must_include_row_permissions(self):
        with self.assertRaisesMessage(
            ValueError,
            "Row and field permissions must also be global permissions: change_customer",
        ):
            PolicyManager.create_policy(
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
                                value="John",
                            )
                        ],
                    )
                ],
                global_permissions=[BloomerpPermission.VIEW],
            )

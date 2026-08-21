from types import SimpleNamespace

from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory

from bloomerp.dataviews.base import DataviewPagination, DataviewRenderState
from bloomerp.dataviews.kanban import KanbanDataviewRenderer
from bloomerp.field_types.lookups import Lookup
from bloomerp.models import (
    ApplicationField,
    FieldPolicy,
    Policy,
    RowPolicy,
    RowPolicyRule,
)
from bloomerp.models.access_control.row_policy_rule import (
    RowPolicyRuleCondition,
    RowPolicyRuleContent,
)
from bloomerp.services.permission_services import ensure_model_permissions
from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestKanbanForeignKeyGroups(BaseBloomerpModelTestCase):
    auto_create_customers = False
    create_foreign_models = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_country_ordering = cls.CountryModel._meta.ordering
        cls._country_model_field = cls.CustomerModel._meta.get_field("country")
        cls._original_limit_choices_to = (
            cls._country_model_field.remote_field.limit_choices_to
        )
        cls.CountryModel._meta.ordering = ["name"]
        cls._country_model_field.remote_field.limit_choices_to = {
            "planet__name": "Earth"
        }

    @classmethod
    def tearDownClass(cls):
        cls.CountryModel._meta.ordering = cls._original_country_ordering
        cls._country_model_field.remote_field.limit_choices_to = (
            cls._original_limit_choices_to
        )
        super().tearDownClass()

    def extendedSetup(self):
        self.country_field = ApplicationField.get_by_field(
            self.CustomerModel,
            "country",
        )

    def test_foreign_key_groups_include_empty_allowed_values_in_model_order(self):
        """
        Use case: A Kanban groups by a foreign key with unused eligible values.
        Expected result: Every eligible value renders in model order with its count.
        """
        # 1. Create one card, leaving other eligible countries unused.
        belgium = self.CountryModel.objects.get(name="Belgium")
        self.CustomerModel.objects.create(
            first_name="First",
            last_name="Customer",
            age=20,
            country=belgium,
        )

        # 2. Build the foreign-key Kanban groups as a superuser.
        groups = KanbanDataviewRenderer.build_groups(
            self.CustomerModel.objects.all(),
            self.country_field,
            user=self.admin_user,
        )

        # 3. Verify ordering, empty lanes, and limit_choices_to filtering.
        self.assertEqual(
            [(group["label"], group["count"]) for group in groups],
            [("Belgium", 1), ("Brazil", 0), ("Netherlands", 0)],
        )

    def test_foreign_key_groups_use_related_row_permissions(self):
        """
        Use case: A user can view only one otherwise eligible foreign-key value.
        Expected result: Only that value is available as a Kanban lane.
        """
        # 1. Create a row policy granting access only to Netherlands.
        ensure_model_permissions(self.CountryModel)
        content_type = ContentType.objects.get_for_model(self.CountryModel)
        name_field = ApplicationField.get_by_field(self.CountryModel, "name")
        field_policy = FieldPolicy.objects.create(
            content_type=content_type,
            name="Kanban country fields",
            rule={},
        )
        row_policy = RowPolicy.objects.create(
            content_type=content_type,
            name="Kanban country rows",
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule=RowPolicyRuleContent(
                connector="OR",
                conditions=[
                    RowPolicyRuleCondition(
                        application_field_id=str(name_field.pk),
                        operator=Lookup.EQUALS.value.id,
                        value="Netherlands",
                    )
                ],
            ).model_dump(),
        )
        row_rule.add_permission(
            f"view_{self.CountryModel._meta.model_name}"
        )
        policy = Policy.objects.create(
            name="Kanban country policy",
            description="Restrict visible Kanban lanes",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(self.normal_user)

        # 2. Build the groups using the restricted user.
        groups = KanbanDataviewRenderer.build_groups(
            self.CustomerModel.objects.all(),
            self.country_field,
            user=self.normal_user,
        )

        # 3. Verify row permissions further reduce the eligible lanes.
        self.assertEqual([group["label"] for group in groups], ["Netherlands"])

    def test_more_than_fifty_allowed_values_requires_another_grouping(self):
        """
        Use case: A grouping field exposes fifty-one eligible foreign-key values.
        Expected result: No partial board renders and the user sees the limit message.
        """
        # 1. Add forty-eight eligible countries to the three existing eligible values.
        earth = self.PlanetModel.objects.get(name="Earth")
        self.CountryModel.objects.bulk_create([
            self.CountryModel(name=f"Country {index}", planet=earth)
            for index in range(48)
        ])

        # 2. Build a renderer for the configured foreign-key grouping.
        request = RequestFactory().get("/")
        request.user = self.admin_user
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        renderer = KanbanDataviewRenderer(DataviewRenderState(
            request=request,
            content_type_id=content_type.pk,
            content_type=content_type,
            model=self.CustomerModel,
            preference=SimpleNamespace(view_type="kanban", options={}),
            queryset=self.CustomerModel.objects.all(),
            fields=SimpleNamespace(
                accessible_fields=[(self.country_field, True)],
                visible_fields=[],
            ),
            render_fields=[],
            avatar_field=None,
            options=SimpleNamespace(
                group_by_field_id=self.country_field.pk,
                page_size=25,
            ),
        ))

        # 3. Render the board and verify the limit state.
        html = renderer.render(DataviewPagination(
            queryset=self.CustomerModel.objects.all()
        ))
        self.assertIn(
            "This field has more than 50 values. Choose another grouping field.",
            html,
        )
        self.assertNotIn('class="kanban-column ', html)

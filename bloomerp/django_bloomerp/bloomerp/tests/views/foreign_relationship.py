from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.fields.reverse_related import ManyToOneRel
from django.test import RequestFactory

from bloomerp.field_types import Lookup
from bloomerp.models import ApplicationField, FieldPolicy, Policy, RowPolicy, RowPolicyRule
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.views.detail.foreign_relationship import ForeignRelationshipView


class TestForeignRelationshipView(BaseBloomerpModelTestCase):
    auto_create_customers = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.NoteModel = create_test_models(
            app_label="bloomerp",
            model_defs={
                "RelationshipNote": {
                    "customer": models.ForeignKey(cls.CustomerModel, on_delete=models.CASCADE),
                    "name": models.CharField(max_length=100),
                }
            },
            use_bloomerp_base=True,
        )["RelationshipNote"]
        cls._register_dynamic_model_routes([cls.NoteModel])

    def extendedSetup(self):
        self._ensure_permissions_for_model(self.CustomerModel)
        self.customer = self.CustomerModel.objects.create(
            first_name="Alice",
            last_name="Example",
            age=31,
        )
        self.note = self.NoteModel.objects.create(
            customer=self.customer,
            name="Related note",
        )

        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        relationship_field = next(
            field
            for field in self.CustomerModel._meta.get_fields()
            if isinstance(field, ManyToOneRel)
            and field.related_model == self.NoteModel
            and field.field.name == "customer"
        )
        self.attribute_name = relationship_field.get_accessor_name()
        self.permission_field_name = relationship_field.name
        self.fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }
        self.factory = RequestFactory()

    def _ensure_permissions_for_model(self, model):
        content_type = ContentType.objects.get_for_model(model)
        for perm in model._meta.default_permissions:
            Permission.objects.get_or_create(
                codename=f"{perm}_{model._meta.model_name}",
                content_type=content_type,
                defaults={"name": f"Can {perm} {model._meta.verbose_name}"},
            )

    def grant_view_policy(self, *, field_names):
        field_policy = FieldPolicy.objects.create(
            content_type=self.content_type,
            name=f"Field policy for {self.normal_user.username}",
            rule={
                str(self.fields_by_name[field_name].pk): [f"view_{self.CustomerModel._meta.model_name}"]
                for field_name in field_names
            },
        )
        row_policy = RowPolicy.objects.create(
            content_type=self.content_type,
            name=f"Row policy for {self.normal_user.username}",
        )
        created_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "application_field_id": str(self.fields_by_name["first_name"].pk),
                "operator": Lookup.EQUALS.value.id,
                "value": self.customer.first_name,
            },
        )
        created_rule.add_permission(f"view_{self.CustomerModel._meta.model_name}")

        policy = Policy.objects.create(
            name=f"Policy for {self.normal_user.username}",
            description="Foreign relationship view policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(self.normal_user)
        policy.global_permissions.add(
            Permission.objects.get(
                content_type=self.content_type,
                codename=f"view_{self.CustomerModel._meta.model_name}",
            )
        )
        return policy

    def build_view(self):
        request = self.factory.get("/")
        request.user = self.normal_user

        view = ForeignRelationshipView()
        view.request = request
        view.kwargs = {"pk": self.customer.pk}
        view.args = ()
        view.model = self.CustomerModel
        view.related_model = self.NoteModel
        view.attribute_name = self.attribute_name
        view.relationship_field_name = "customer"
        view.permission_fields = [(self.permission_field_name, "view")]
        view.object = self.customer
        return view

    def test_has_permission_requires_field_permission_for_relationship_field(self):
        self.grant_view_policy(field_names=[])
        view = self.build_view()

        self.assertFalse(view.has_permission())

    def test_has_permission_allows_when_user_can_view_object_and_relationship_field(self):
        self.grant_view_policy(field_names=[self.permission_field_name])
        view = self.build_view()

        self.assertTrue(view.has_permission())
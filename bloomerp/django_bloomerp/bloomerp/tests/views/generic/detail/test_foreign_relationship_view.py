from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.fields.reverse_related import ManyToOneRel
from django.test import override_settings
from django.urls import clear_url_caches, path

from bloomerp.lookups import builtins as lookups
from bloomerp.models import ApplicationField, FieldPolicy, Policy, RowPolicy, RowPolicyRule
from bloomerp.tests.base import ExpectedResult, RequestScenario, RequestTestCaseMixin
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels
from bloomerp.tests.utils.dynamic_models import create_test_models
from bloomerp.views.generic.detail.foreign_relationship import ForeignRelationshipView
from config.urls import urlpatterns as project_urlpatterns


urlpatterns = list(project_urlpatterns)


@override_settings(ROOT_URLCONF=__name__)
class TestForeignRelationshipView(RequestTestCaseMixin, BaseBloomerpTestCaseWithModels):
    """Behavior contract for relationship-field authorization."""

    view_name = "test_foreign_relationship"
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
        relationship = next(
            field
            for field in cls.CustomerModel._meta.get_fields()
            if isinstance(field, ManyToOneRel)
            and field.related_model == cls.NoteModel
            and field.field.name == "customer"
        )
        cls.permission_field_name = relationship.name
        urlpatterns.append(
            path(
                "relationships/<uuid:pk>/",
                ForeignRelationshipView.as_view(
                    model=cls.CustomerModel,
                    related_model=cls.NoteModel,
                    attribute_name=relationship.get_accessor_name(),
                    relationship_field_name="customer",
                    permission_field_name=cls.permission_field_name,
                ),
                name=cls.view_name,
            )
        )
        clear_url_caches()

    @classmethod
    def tearDownClass(cls):
        urlpatterns.pop()
        clear_url_caches()
        super().tearDownClass()

    def extendedSetup(self):
        self._ensure_permissions_for_model(self.CustomerModel)
        self.customer = self.CustomerModel.objects.create(
            first_name="Alice", last_name="Example", age=31
        )
        self.NoteModel.objects.create(customer=self.customer, name="Related note")
        self.content_type = ContentType.objects.get_for_model(self.CustomerModel)
        self.fields_by_name = {
            field.field: field
            for field in ApplicationField.get_for_model(self.CustomerModel)
        }

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="Relationship page requires permission on the reverse field",
                description=(
                    "UC: A user may view an object but not its reverse relationship field.\n"
                    "Expected Result: The relationship page returns 403."
                ),
                user=self.normal_user,
                view_kwargs={"pk": self.customer.pk},
                prepare=self.grant_object_only_policy,
                expected=ExpectedResult(status_code=403),
            ),
            RequestScenario(
                name="Relationship page opens when object and reverse field are viewable",
                description=(
                    "UC: A user may view both an object and its reverse relationship field.\n"
                    "Expected Result: The relationship page renders the related-object component."
                ),
                user=self.normal_user,
                view_kwargs={"pk": self.customer.pk},
                prepare=self.grant_relationship_policy,
                expected=ExpectedResult(response_validators=self.relationship_context_is_configured),
            ),
        ]

    def _ensure_permissions_for_model(self, model):
        content_type = ContentType.objects.get_for_model(model)
        for action in model._meta.default_permissions:
            Permission.objects.get_or_create(
                codename=f"{action}_{model._meta.model_name}",
                content_type=content_type,
                defaults={"name": f"Can {action} {model._meta.verbose_name}"},
            )

    def relationship_context_is_configured(self, response):
        return (
            response.context["filters"] == {"customer": str(self.customer.pk)}
            and response.context["args"] == {"hide_filters": "customer"}
            and response.context["foreign_content_type_id"]
            == ContentType.objects.get_for_model(self.NoteModel).pk
        )

    def grant_object_only_policy(self, _scenario):
        self.grant_view_policy(field_names=[])

    def grant_relationship_policy(self, _scenario):
        self.grant_view_policy(field_names=[self.permission_field_name])

    def grant_view_policy(self, *, field_names):
        codename = f"view_{self.CustomerModel._meta.model_name}"
        field_policy = FieldPolicy.objects.create(
            content_type=self.content_type,
            name=f"Relationship fields for {self.normal_user.username}",
            rule={
                str(self.fields_by_name[field_name].pk): [codename]
                for field_name in field_names
            },
        )
        row_policy = RowPolicy.objects.create(
            content_type=self.content_type,
            name=f"Relationship rows for {self.normal_user.username}",
        )
        row_rule = RowPolicyRule.objects.create(
            row_policy=row_policy,
            rule={
                "connector": "OR",
                "conditions": [
                    {
                        "application_field_id": str(self.fields_by_name["first_name"].pk),
                        "operator": lookups.EQUALS.id,
                        "value": self.customer.first_name,
                    }
                ],
            },
        )
        row_rule.add_permission(codename)
        policy = Policy.objects.create(
            name=f"Relationship policy for {self.normal_user.username}",
            description="Foreign relationship view policy",
            row_policy=row_policy,
            field_policy=field_policy,
        )
        policy.assign_user(self.normal_user)
        policy.global_permissions.add(
            Permission.objects.get(content_type=self.content_type, codename=codename)
        )

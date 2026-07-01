import asyncio

from django.test import SimpleTestCase
from django.urls import resolve

from bloomerp.models.project_management.initiative import Initiative
from bloomerp.utils.api import generate_model_viewset_class, generate_serializer
from bloomerp.views.api.api_views import BloomerpModelViewSet


class GeneratedModelApiRouteTests(SimpleTestCase):
    def test_generated_viewset_can_be_built_in_async_context(self):
        async def build_viewset():
            return generate_model_viewset_class(
                model=Initiative,
                serializer=generate_serializer(Initiative),
                base_viewset=BloomerpModelViewSet,
            )

        viewset = asyncio.run(build_viewset())

        self.assertEqual(viewset.model, Initiative)

    def test_generated_model_endpoint_resolves(self):
        match = resolve("/api/initiatives/")

        self.assertEqual(match.url_name, "initiatives-list")

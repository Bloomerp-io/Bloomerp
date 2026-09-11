from typing import Optional

from django.db.models import Model
from django.urls import reverse
from django.db import models

from bloomerp.modules.definition import module_registry
from bloomerp.router import RouteType, router
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels
from bloomerp.tests.base.request_test_case_mixin import (
    ModelRequestScenario,
    ModuleRequestScenario,
    RequestScenario,
    RequestTestCaseMixin,
)


class BloomerpViewTestCase(RequestTestCaseMixin, BaseBloomerpTestCaseWithModels):
    """Base class for declarative tests of routed Bloomerp views."""

    view_name: str | None = None
    route_type = RouteType.APP
    model: type[Model] | None = None
    module = None

    def get_test_case_module(self, module=None):
        """Resolve a configured module object or registry ID."""
        selected_module = self.module if module is None else module
        if isinstance(selected_module, str):
            resolved_module = module_registry.get(selected_module)
            if resolved_module is None:
                raise AssertionError(
                    f"Module {selected_module!r} is not registered"
                )
            return resolved_module
        return selected_module

    def get_route(self, view_name: str | None = None, *, model=None, module=None):
        """Resolve the concrete route for this test's model/module context."""
        selected_view_name = view_name or self.view_name
        selected_model = self.model if model is None else model
        selected_module = self.get_test_case_module(module)
        candidates = [
            route
            for route in router.get_routes_by_type(self.route_type)
            if selected_view_name in {route.base_url_name, route.url_name}
            and (
                selected_model is None
                or route.model is selected_model
            )
            and (selected_module is None or route.module == selected_module)
        ]
        if len(candidates) != 1:
            raise AssertionError(
                f"Expected one {self.route_type.value!r} route named "
                f"{selected_view_name!r}, found {len(candidates)}."
            )
        return candidates[0]

    def get_endpoint(
        self,
        view_name: str,
        kwargs: dict | None,
        setup: RequestScenario | None = None,
    ) -> str:
        """Reverse the concrete route selected by the test context."""
        model = setup.model if isinstance(setup, ModelRequestScenario) else None
        module = setup.module if isinstance(setup, ModuleRequestScenario) else None
        route = self.get_route(view_name, model=model, module=module)
        return reverse(viewname=route.url_name, kwargs=kwargs or self.get_view_kwargs())

    def test_route_registration(self) -> None:
        """
        Use case: A generated view test selects a route context.
        Expected result: Exactly one matching concrete route is registered.
        """
        # 1. Do not execute the reusable base class itself.
        if self.view_name is None:
            return

        # 2. Require the context needed by specialized route families.
        if self.route_type in {
            RouteType.MODEL,
            RouteType.DETAIL,
            RouteType.API_MODEL,
            RouteType.API_DETAIL,
        }:
            if self.model is None:
                self.skipTest("Set model to test this route")
        if self.route_type == RouteType.MODULE and self.module is None:
            self.skipTest("Set module to test this route")

        # 3. Resolve and validate the selected route registration.
        route = self.get_route()
        self.assertEqual(route.route_type, self.route_type)
        if self.model is not None:
            self.assertIs(route.model, self.model)
        if self.module is not None:
            self.assertEqual(route.module, self.get_test_case_module())
            
    def get_view_kwargs(self) -> Optional[dict]:
        """Sets the default view kwargs for all tests if not given in setup

        Returns:
            dict: the optional dictionary
        """
        return None
        


class BloomerpModelViewTestCase(BloomerpViewTestCase):
    """Base class for model-level routes."""

    route_type = RouteType.MODEL


class BloomerpDetailViewTestCase(BloomerpViewTestCase):
    """Base class for object-detail routes."""
    test_object = None
    route_type = RouteType.DETAIL
    
    def create_test_object(self) -> models.Model | None:
        """Returns default object for all test cases.
        Is used to automatically set the view kwargs.
    

        Returns:
            models.Model: an instance of a model
        """
    
    def get_test_object(self) -> models.Model | None:
        if self.test_object: 
            return self.test_object
        self.test_object = self.create_test_object()
        return self.test_object
        
    
    def get_view_kwargs(self):
        obj = self.get_test_object()
        
        if obj:
            return {
                "pk" : obj.pk
            }
        return None
        


class BloomerpModuleViewTestCase(BloomerpViewTestCase):
    """Base class for module-level routes."""

    route_type = RouteType.MODULE


class BloomerpAPIViewTestCase(BloomerpViewTestCase):
    """Base class for application-level API routes."""

    route_type = RouteType.API


class BloomerpAPIModelViewTestCase(BloomerpModelViewTestCase):
    """Base class for model-level API routes."""

    route_type = RouteType.API_MODEL


class BloomerpAPIDetailViewTestCase(BloomerpDetailViewTestCase):
    """Base class for object-detail API routes."""

    route_type = RouteType.API_DETAIL

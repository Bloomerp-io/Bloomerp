from bloomerp.tests.base.component_test_case import BloomerpComponentTestCase
from bloomerp.tests.base.core_test_case import (
    BaseBloomerpTestCaseWithModels,
    BloomerpChannelTestCase,
)
from bloomerp.tests.base.e2e_test_case import (
    BloomerpE2ETestCase,
    E2EAction,
    E2ERequestSetup,
)
from bloomerp.tests.base.dataview_test_case import BloomerpDataviewTestCase
from bloomerp.tests.base.model_field_test_case import BloomerpModelFieldTestCase
from bloomerp.tests.base.model_test_case import (
    BaseBloomerpModelTestCase,
    BloomerpModelTestCase,
)
from bloomerp.tests.base.request_test_case_mixin import (
    ExpectedResult,
    ModelRequestSetup,
    ModuleRequestSetup,
    RequestSetup,
    RequestPreparation,
    RequestTestCaseMixin,
    ResponseValidator,
)
from bloomerp.tests.base.view_test_case import (
    BloomerpAPIDetailViewTestCase,
    BloomerpAPIModelViewTestCase,
    BloomerpAPIViewTestCase,
    BloomerpDetailViewTestCase,
    BloomerpModelViewTestCase,
    BloomerpModuleViewTestCase,
    BloomerpViewTestCase,
)
from bloomerp.tests.base.widget_test_case import BloomerpWidgetTestCase
from bloomerp.tests.base.workflow_node_test_case import (
    BloomerpWorkflowNodeTestCase,
    WorkflowNodeSimulation,
)


# Backwards-compatible names used by existing projects.
BaseBloomerpComponentTest = BloomerpComponentTestCase
BaseBloomerpWidgetTestCase = BloomerpWidgetTestCase

__all__ = [
    "BaseBloomerpComponentTest",
    "BaseBloomerpModelTestCase",
    "BaseBloomerpTestCaseWithModels",
    "BaseBloomerpWidgetTestCase",
    "BloomerpChannelTestCase",
    "BloomerpComponentTestCase",
    "BloomerpDataviewTestCase",
    "BloomerpAPIDetailViewTestCase",
    "BloomerpAPIModelViewTestCase",
    "BloomerpAPIViewTestCase",
    "BloomerpDetailViewTestCase",
    "BloomerpE2ETestCase",
    "E2EAction",
    "E2ERequestSetup",
    "BloomerpModelFieldTestCase",
    "BloomerpModelTestCase",
    "BloomerpModelViewTestCase",
    "BloomerpModuleViewTestCase",
    "BloomerpViewTestCase",
    "BloomerpWidgetTestCase",
    "BloomerpWorkflowNodeTestCase",
    "ExpectedResult",
    "ModelRequestSetup",
    "ModuleRequestSetup",
    "RequestPreparation",
    "RequestSetup",
    "RequestTestCaseMixin",
    "ResponseValidator",
    "WorkflowNodeSimulation",
]

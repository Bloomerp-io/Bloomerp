# Dataview test cases

Use `BloomerpDataviewTestCase` for the universal registration contract of a
dataview type. Unlike most other generated bases, it does not define a scenario
list: setting the registry key is enough to run the common validity check.

## Generated skeleton

```python
from bloomerp.tests.base import BloomerpDataviewTestCase


class TestGanttDataview(BloomerpDataviewTestCase):
    dataview_key = "gantt"
```

The base verifies that:

- the key exists in the dataview registry;
- the returned definition uses that key;
- a renderer class is configured;
- a configuration class is configured.

Add ordinary focused test methods below the generated class when a dataview
has behavior beyond registration, such as configuration validation or renderer
output.

Use request tests for dataview endpoints and end-to-end tests for interactive
features such as switching views, drag-and-drop, filtering, or browser-side
state. Do not add a generic scenario abstraction merely to wrap one registry
lookup.

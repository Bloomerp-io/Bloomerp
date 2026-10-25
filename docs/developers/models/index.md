# Model configuration
## Field rendering settings

Model configuration can manage application-field rendering templates:

```python
from bloomerp.models.definition import BloomerpModelConfig, FieldSettings

bloomerp_config = BloomerpModelConfig(
    field_settings=[
        FieldSettings(field="amount", advanced_rendering="<strong>{{ value }}</strong>"),
    ],
)
```

`save_application_fields` applies these declarations whenever it synchronizes
metadata. A declared setting with `advanced_rendering=None` or an empty string
clears the override. Fields without a declaration retain their saved rendering.
Templates use the same syntax validation as ApplicationField overrides.

from typing import Optional

from pydantic import BaseModel

class BloomerpConfig(BaseModel):
    """
    Configuration class to be set on the settings. This contains all the necessary configurable settings for bloomerp.

    Settings are:
    - **auto_generate_api_endpoints** : whether to automatically generate API endpoints for all models. If True, API endpoints will be generated for all models in the application. If False, no API endpoints will be generated. If None, API endpoints will be generated for all models that do not have a custom API endpoint defined. Note that this can be overridden on a per model basis by setting the `auto_generate_api_endpoint` attribute on the model's configuration.
    - **vite_dev_server_url**: the URL of the Vite development server. This is used for hot module replacement (HMR) during development. The default value is 'http://localhost:5173'. This setting is only used if BLOOMERP_VITE_DEV_SERVER_URL is not set in the settings.

    Usage (in settings.py)
    ```python
    from bloomerp.config.definition import BloomerpConfig

    bloomerp_config = BloomerpConfig(
        ...
    )
    ```
    """

    auto_generate_api_endpoints : bool = True

    vite_dev_server_url : Optional[str] = 'http://localhost:5173'
    




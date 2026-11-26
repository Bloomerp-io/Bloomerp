# Proposed scaffolding parameters for an application model.
# app: str | None = None - Target app; resolve with cli.app._utils.resolve_app_dir.
# name: str - Python module name and generated model class prefix.
# module: str | None = None - Existing module ID or BloomerpModule import path.
# base_class: str = "bloomerp.models.BloomerpModel" - Model superclass import path.
# verbose_name: str | None = None - Singular model label; derive when omitted.
# verbose_name_plural: str | None = None - Plural model label; derive when omitted.
# db_table: str | None = None - Optional explicit Django database table name.
# icon: str = "fa fa-cube" - Icon for the generated BloomerpModelConfig.
# description: str | None = None - Optional model description.
# abstract: bool = False - Whether to generate an abstract Django model.
# Registration: Django model discovery and module_registry through bloomerp_config.

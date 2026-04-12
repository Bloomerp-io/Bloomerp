from .definition import ModuleConfig

class MiscModule(ModuleConfig):
    id: str = "misc"
    code: str = "misc"
    icon: str = "fa-solid fa-ellipsis-h"
    name: str = "Miscellaneous"
    description: str = "A collection of miscellaneous features and tools that don't fit into other specific modules."
    
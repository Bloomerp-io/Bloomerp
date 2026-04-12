from .definition import ModuleConfig

class DataModule(ModuleConfig):
    id: str = "data"
    code: str = "data"
    icon: str = "fa-solid fa-database"
    name: str = "Data Management"
    description: str = "Tools and features for managing and analyzing data within the ERP system."
    visible: bool = True
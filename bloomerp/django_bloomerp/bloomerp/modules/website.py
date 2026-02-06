from .definition import ModuleConfig

class WebsiteModule(ModuleConfig):
    id: str = "website"
    code: str = "website"
    icon: str = "fa-solid fa-globe"
    name: str = "Website"
    description: str = "Tools and features for building and managing websites within the ERP system."
    visible: bool = True
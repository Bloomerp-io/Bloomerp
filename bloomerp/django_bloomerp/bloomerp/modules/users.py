from .definition import ModuleConfig

class UsersModule(ModuleConfig):
    id: str = "users"
    code: str = "users"
    icon: str = "fa-solid fa-users"
    name: str = "Users"
    description: str = "Manage users, roles, and permissions within the ERP system."
    
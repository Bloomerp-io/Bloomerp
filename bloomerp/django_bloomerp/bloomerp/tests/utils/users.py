from bloomerp.models.users import User
from django.contrib.auth.hashers import make_password

def create_admin() -> User:
    return User.objects.create_superuser(
        username="admin",
        password=make_password("testpass123"),
        first_name="Supreme",
        last_name="Leader"
    )
    
def create_normal_user() -> User:
    return User.objects.create(
        username="johndoe",
        password=make_password("testpass123"),
        first_name="John",
        last_name="Doe"
    )
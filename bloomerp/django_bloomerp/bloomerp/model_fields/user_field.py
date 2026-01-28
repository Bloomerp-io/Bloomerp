from django.db import models
from django.conf import settings

class UserField(models.ForeignKey):
    """
    A user field is a simple foreign key
    field that links to a particular user

    # TODO: In the apps startup logic, add a warning message if
    the developers tries to use a ForeignKey to the User model
    instead of this UserField.
    """
    def __init__(self, *args, **kwargs):
        # Avoid calling get_user_model() during app/model import.
        # Using the swappable model label keeps Django startup/migrations safe.
        kwargs.setdefault('to', settings.AUTH_USER_MODEL)
        super().__init__(*args, **kwargs)
    
from bloomerp.models.auth import AbstractBloomerpUser
from django.db.models import Model
from bloomerp.utils.models import model_name_singular_underline


def can_view_model(user:AbstractBloomerpUser, model:Model) -> bool:
    """
    This function returns True if the user has permission to view the model.
    """
    return user.has_perm('view_%s' % model_name_singular_underline(model))

def can_add_model(user:AbstractBloomerpUser, model:Model) -> bool:
    """
    This function returns True if the user has permission to add the model.
    """
    return user.has_perm('add_%s' % model_name_singular_underline(model))

def can_change_model(user:AbstractBloomerpUser, model:Model) -> bool:
    """
    This function returns True if the user has permission to change the model.
    """
    return user.has_perm('change_%s' % model_name_singular_underline(model))

def can_delete_model(user:AbstractBloomerpUser, model:Model) -> bool:
    """
    This function returns True if the user has permission to delete the model.
    """
    return user.has_perm('delete_%s' % model_name_singular_underline(model))
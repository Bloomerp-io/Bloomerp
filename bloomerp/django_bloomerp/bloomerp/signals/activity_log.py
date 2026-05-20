from typing import Optional, Any

from django.db.models import Model
from django.db.models.signals import pre_delete, pre_save, post_delete, post_save
from bloomerp.middleware import current_request
from django.dispatch import receiver
import uuid

from bloomerp.services.activity_log_services import ActivityLogManager


TRANSIENT_ATTRIBUTE_NAME = "_event_id"
_data : dict[str, ActivityLogManager] = {}

def set_transient_attribute(instance: Model) -> Optional[str]:
    if not hasattr(instance, TRANSIENT_ATTRIBUTE_NAME):
        id = str(uuid.uuid4())
        setattr(instance, TRANSIENT_ATTRIBUTE_NAME, id)
        return id
    
    return None

def get_transient_attribute(instance: Model) -> Optional[str]:
    if hasattr(instance, TRANSIENT_ATTRIBUTE_NAME):
        return getattr(instance, TRANSIENT_ATTRIBUTE_NAME)
    
    return None

def clear_transient_attribute(instance: Model) -> None:
    if hasattr(instance, TRANSIENT_ATTRIBUTE_NAME):
        delattr(instance, TRANSIENT_ATTRIBUTE_NAME)

def capture_before_state(instance: Model, event_id: str) -> None:
    """Fetch the database row to get the true before-state."""
    before_state = {}
    
    # For new instances, no database row exists yet
    if instance.pk is None:
        for field in instance._meta.concrete_fields:
            before_state[field.name] = None
    else:
        # Fetch the current database row to get original values
        db_instance = instance.__class__.objects.get(pk=instance.pk)
        for field in instance._meta.concrete_fields:
            before_state[field.name] = getattr(db_instance, field.name, None)
    
    _data[event_id] = before_state

def compute_field_changes(instance: Model, event_id: str) -> list[dict[str, Any]]:
    """Compare before/after state and return list of field changes."""
    before_state = _data.get(event_id, {})
    changes = []
    
    for field in instance._meta.concrete_fields:
        field_name = field.name
        before_value = before_state.get(field_name)
        after_value = getattr(instance, field_name, None)
        
        # Only record if the value changed
        if before_value != after_value:
            changes.append({
                "field": field_name,
                "from": before_value,
                "to": after_value,
            })
    
    # Clean up stored state
    if event_id in _data:
        del _data[event_id]
    
    return changes


@receiver(pre_save)
def before_save_of_object(sender, instance: Model, **kwargs):
    manager = ActivityLogManager(instance, current_request())
    
    if not ActivityLogManager.should_record_change(instance._meta.model):
        return
    
    # Calculate changes from serialized before/after snapshots
    manager.set_changes()
    
    # Set the transient attribute
    event_id = set_transient_attribute(instance)
    
    if event_id is not None:
        _data[event_id] = manager
    

@receiver(post_save)
def after_save_of_object(sender, instance: Model, created: bool, **kwargs):
    id = get_transient_attribute(instance)
    if not id: 
        return
    
    try:
        manager = _data[id]
        manager.persist()
        
        del _data[id]
        clear_transient_attribute(instance)
        
    except Exception as e:
        print(e)


@receiver(pre_delete)
def before_delete_of_object(sender, instance: Model, **kwargs):
    manager = ActivityLogManager(instance, current_request())

    if not ActivityLogManager.should_record_change(instance._meta.model):
        return

    manager.set_delete()
    event_id = set_transient_attribute(instance)

    if event_id is not None:
        _data[event_id] = manager


@receiver(post_delete)
def after_delete_of_object(sender, instance: Model, **kwargs):
    id = get_transient_attribute(instance)
    if not id:
        return

    try:
        manager = _data[id]
        manager.persist()

        del _data[id]
        clear_transient_attribute(instance)

    except Exception as e:
        print(e)
    


    
    


    
    

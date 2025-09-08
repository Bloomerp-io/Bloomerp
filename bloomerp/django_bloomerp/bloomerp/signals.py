from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model

def notification_handler(
        sender, 
        instance : Model, 
        created: bool,
        **kwargs):
    if created:
        # Do something
        print('New notification created!', instance, sender)
    else:
        # Do something
        print('Notification updated!', instance, sender)

# Connect all models to the notification handler

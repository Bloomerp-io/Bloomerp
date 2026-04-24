from django.urls import re_path

from . import consumers

# TODO: Refactor this
websocket_urlpatterns = [
    re_path(r'^ws/notifications/$', consumers.NotificationsConsumer.as_asgi()),
]

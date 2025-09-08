import re
import uuid
from django.urls.resolvers import URLPattern

class IntOrUUIDConverter:
    regex = '[0-9]+|[0-9a-f-]{36}'

    def to_python(self, value):
        try:
            # Try to convert the value to an integer
            return int(value)
        except ValueError:
            # If it fails, try to convert it to a UUID
            return uuid.UUID(value)

    def to_url(self, value):
        return str(value)
    


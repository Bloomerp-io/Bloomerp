


from bloomerp.instant_messaging.definition import BaseIMAdapter


class InternalIMAdapter(BaseIMAdapter):
    
    def validate_connection(self):
        return True
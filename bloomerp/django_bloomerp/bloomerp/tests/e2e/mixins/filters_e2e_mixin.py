


from typing import Any
from bloomerp.tests.base import E2EAction

class FilterE2EMixin:
    
    
    def click_filter(self) -> E2EAction:
        pass
    
    def select_filter_field(self, field:str, level:int=0) -> E2EAction:
        pass
    
    def select_filter_lookup(self, lookup_id:str, level:int=0) -> E2EAction:
        pass
    
    def set_filter_value(self, value:Any, level:int=0) -> E2EAction:
        pass
    
    def apply_filters(self, validators) -> E2EAction:
        pass
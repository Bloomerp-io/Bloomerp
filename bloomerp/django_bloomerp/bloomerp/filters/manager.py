from typing import Optional

from bloomerp.filters.compiler import compile_filters
from django.db.models import Model, QuerySet
from bloomerp.filters.parser import deserialize_filters


class ModelFilterManager:
    model : type[Model]

    def __init__(self, model: type[Model]):
        self.model = model
        
    
    def filter(self, args: dict, queryset: Optional[QuerySet[Model]] = None):
        """_summary_

        Args:
            get_args (dict): _description_
        """
        filter_str = args.get("filter", None)
        
        if not filter_str:
            return queryset
        
        filters = deserialize_filters(filter_str)
        
        compiled = compile_filters(filters)
        
        return queryset.filter(
            **compiled
        )
        
    
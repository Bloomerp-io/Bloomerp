"""
The goal of the parser is to resolve GET requests into 
"""
import json
from bloomerp.filters.definition import FilterCondtion, Filters


def deserialize_filters(filters:str) -> Filters:
    """Parses the JSON into filters

    Args:
        filter (str): the json serialized list of filter groups

    Returns:
        Filters: a list of filters containing conditions
    """
    parsed = []
    filters = json.load(filter)
    for filter in filters:
        parsed.append(
            FilterCondtion.model_dump(
                filter
            )
        )
        
    return parsed
        



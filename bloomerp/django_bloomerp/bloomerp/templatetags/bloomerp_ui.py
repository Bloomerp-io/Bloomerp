from django import template
from typing import List
from django.utils.safestring import mark_safe

register = template.Library()

from typing import List

@register.inclusion_tag('bloomerp_ui/searchable_table.html')
def searchable_table(object_list: List[object], attributes: str, dict:bool=False, func:str=None):
    '''Returns a searchable table.

    Example usage:
    {% searchable_table object_list 'attribute1,attribute2.subattribute' %}
    '''
    # Init context
    attributes_list: List[str] = attributes.split(',')

    # Create table headers
    headers = [attr.replace('.', ' ').capitalize() for attr in attributes_list]

    # Populate table rows
    rows = []
    for obj in object_list:
        row = []
        for attribute in attributes_list:
            # Split by dot and traverse the nested attributes
            if dict:
                value = obj[attribute]
            else:
                value = get_nested_attribute(obj, attribute)

            if func:
                value = value.__getattribute__(func)()
            row.append(mark_safe(value))
        rows.append(row)

    context = {
        'headers': headers,
        'list': rows
    }
    return context


def get_nested_attribute(obj, attribute_path: str):
    """
    Recursively get nested attributes based on dot-separated path.
    
    :param obj: Object to retrieve attribute from.
    :param attribute_path: Dot-separated string of attribute names.
    :return: Value of the nested attribute or None if not found.
    """
    try:
        for attr in attribute_path.split('.'):
            obj = getattr(obj, attr)
        return obj
    except AttributeError:
        return None

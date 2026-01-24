from typing import Any
from django.http import HttpRequest, HttpResponse
from django.forms import Form
from django.shortcuts import render

def parse_bool_parameter(value : Any, default_value=False) -> bool:
    """
    Function that will parse a string to a boolean value.
    """
    try:
        if isinstance(value, bool):
            return value
        
        if isinstance(value, int):
            return bool(value)
        
        if isinstance(value, str):
            if value.lower() in ['true', '1']:
                return True
            elif value.lower() in ['false', '0']:
                return False
            
        return default_value
    except:
        return default_value    
    
    

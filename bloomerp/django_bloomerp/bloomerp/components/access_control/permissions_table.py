from django.http import HttpRequest
from django.shortcuts import render
from bloomerp.models.access_control import field_policy
from bloomerp.router import router
from rest_framework import serializers

@router.register(
    path='components/permissions-table/',
    name='components_permissions_table'
)
def permissions_table(request:HttpRequest):
    # Some logic here
    
    return render(
        request,
        "components/permissions_table.html"
    )
    
    





    

from django import forms

class BaseWorkflowNodeForm(forms.Form):
    refresh_on_input = False
    
    
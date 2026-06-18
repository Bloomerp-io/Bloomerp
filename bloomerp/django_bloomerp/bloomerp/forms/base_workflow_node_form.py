from django import forms

class BaseWorkflowNodeForm(forms.Form):
    refresh_on_input = False
    
    
    def field_is_set(self, field_name:str) -> bool:
        """Determines whether the field is set with an initial value or not

        Args:
            field_name (str): The name of the field to check.

        Returns:
            bool: True if the field is set with an initial value, False otherwise.
        """
        return self.initial.get(field_name) is not None
    
    
    def set_widget(self, field_name:str, widget:forms.Widget):
        """Utility method to set a widget on a field

        Args:
            field_name (str): The name of the field to set the widget on.
            widget (forms.Widget): The widget to set on the field.
        """
        if field_name in self.fields:
            self.fields[field_name].widget = widget
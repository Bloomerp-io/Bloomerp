from crispy_forms.helper import FormHelper
from bloomerp.models import BloomerpModel
from crispy_forms.layout import Layout, Fieldset, Submit, Div, HTML, Field
from uuid import uuid4
from bloomerp.models import LayoutSection

class BloomerpModelformHelper(FormHelper):
    layout_defined: bool = False

    def __init__(self, layout:list[LayoutSection], *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Disable the form tag
        self.form_tag = False
        
        # Get the field names            
        rows = []
        for section in layout:
            fields = [Field(field_name) for field_name in section.items]
            
            if section.title:
                rows.append(
                    Div(HTML(f"<h1 class='block text-primary-900 font-bold mb-2'>{section.title}</h1>"))
                )
            
            rows.append(Div(
                Div(
                    *fields,
                    css_class=f"grid grid-cols-1 md:grid-cols-{section.columns} gap-2"
                    )
            ))
        
        self.layout = Layout(*rows)
        self.layout_defined = True
    
    def is_defined(self) -> bool:
        return self.layout_defined


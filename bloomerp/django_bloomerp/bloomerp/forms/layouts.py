from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Div, HTML, Field
from bloomerp.models.base_bloomerp_model import LayoutRow

class BloomerpModelformHelper(FormHelper):
    layout_defined: bool = False

    def __init__(self, layout:list[LayoutRow], *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Disable the form tag
        self.form_tag = False
        
        # Get the field names            
        rows = []
        for row in layout:
            fields = [Field(str(item.id)) for item in row.items]
            
            if row.title:
                rows.append(
                    Div(HTML(f"<h1 class='block text-primary-900 font-bold mb-2'>{row.title}</h1>"))
                )
            
            rows.append(Div(
                Div(
                    *fields,
                    css_class=f"grid grid-cols-1 md:grid-cols-{row.columns} gap-2"
                    )
            ))
        
        self.layout = Layout(*rows)
        self.layout_defined = True
    
    def is_defined(self) -> bool:
        return self.layout_defined

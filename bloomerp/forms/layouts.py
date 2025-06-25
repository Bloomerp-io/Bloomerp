from crispy_forms.helper import FormHelper
from bloomerp.models import BloomerpModel
from crispy_forms.layout import Layout, Fieldset, Submit, Div, HTML
from uuid import uuid4

class BloomerpModelformHelper(FormHelper):
    layout_defined: bool = False

    def __init__(self, model: BloomerpModel, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.form_tag = False

        if not model:
            self.layout_defined = False
            return

        content = '''<h3 class="dropdown-toggle form-legend pointer" onclick="document.getElementById('{id}').classList.toggle('hidden')">{title}{asterix}</h3>'''

        fieldsets = []

        if hasattr(model, 'form_layout') and model.form_layout:
            layout = model._get_form_layout()
            if not layout:
                self.layout_defined = False
                return


            for title, item in layout.items():
                id = uuid4()

                field_list = item['fields']
                required = item['required']

                css_class = '' if required else ''
                asterix = '*' if required else ''

                _content = content.format(title=title, id=id, asterix=asterix)

                fieldsets.append(
                    Div(
                        HTML(_content),
                        Fieldset(None, *field_list, css_id=id, css_class=css_class)
                    )
                )

            self.layout = Layout(
                *fieldsets
            )

            self.layout_defined = True
        else:
            self.layout_defined = False

    def is_defined(self) -> bool:
        return self.layout_defined


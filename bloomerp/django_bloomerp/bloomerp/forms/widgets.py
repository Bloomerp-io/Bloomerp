from django import forms
from django.forms import ModelChoiceField
from bloomerp.models.workspaces import Widget, SqlQuery
from django.core.exceptions import ValidationError
from bloomerp.widgets.foreign_field_widget import ForeignFieldWidget
from bloomerp.widgets.text_editor import BloomerpTextEditorWidget
from django.utils.translation import gettext as _

class WidgetForm1(forms.Form):
    query = ModelChoiceField(
        queryset=SqlQuery.objects.all(),
        widget=ForeignFieldWidget(attrs={'model': SqlQuery}),
        help_text=_('The sql query (data) to use for the query')
        
        )
    name = forms.CharField(
        max_length=255,
        help_text=_('The name given to the widget')
        )
    description = forms.CharField(
        widget=BloomerpTextEditorWidget(),
        required=False,
        help_text=_('The description of the widget. Will be displayed in the widget if provided')
        )
    
    def __init__(self, widget:Widget=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if widget:
            self.fields['name'].initial = widget.name
            self.fields['description'].initial = widget.description
            self.fields['query'].initial = widget.query
        

class WidgetForm2(forms.Form):
    output_type = forms.ChoiceField(
        help_text=_('The type of output to display for the widget')
        )
    
    def __init__(self, widget:Widget=None, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if widget:
            self.fields['output_type'].initial = widget.output_type

class WidgetForm3(forms.Form):
    def __init__(self, widget:Widget=None, *args, **kwargs):
        output_type = kwargs.pop('output_type', None)
        query : SqlQuery = kwargs.pop('query', None)

        super().__init__(*args, **kwargs)
        
        if query and output_type:
            # If the output type is table, add a field for the columns
            columns = query.result_dict()['columns']

            choices = [(None, '---------')] + [(col, col) for col in columns]

            if output_type == 'table':
                self.fields['columns'] = forms.MultipleChoiceField(
                    choices=[(col, col) for col in columns]
                    )
                self.fields['limit'] = forms.IntegerField(min_value=1, required=False, help_text=_('The number of rows to display in the table'), initial=10)
            elif output_type == 'scatter' or output_type == 'line' or output_type == 'bar':
                self.fields['x'] = forms.ChoiceField(choices=choices)
                self.fields['y'] = forms.ChoiceField(choices=choices)
                self.fields['group_by'] = forms.ChoiceField(choices=choices, required=False)
            elif output_type == 'pie':
                self.fields['x'] = forms.ChoiceField(choices=choices)
                self.fields['group_by'] = forms.ChoiceField(choices=choices)
            elif output_type == 'histogram':
                self.fields['x'] = forms.ChoiceField(choices=choices)
            elif output_type == 'value':
                self.fields['color'] = forms.CharField(widget=forms.TextInput(attrs={'type': 'color'}))
                self.fields['icon'] = forms.CharField(required=False, initial='bi bi-bar-chart-fill')
                self.fields['aggregate'] = forms.ChoiceField(choices=Widget.VALUE_AGGREGATE_CHOICES)
                self.fields['column'] = forms.ChoiceField(choices=choices, required=True)
                self.fields['prefix'] = forms.CharField(max_length=255, required=False)
                self.fields['suffix'] = forms.CharField(max_length=255, required=False)
        
    def clean(self):
        cleaned_data = super().clean()
        output_type = cleaned_data.get('output_type')
        columns = cleaned_data.get('columns')
        x = cleaned_data.get('x')
        y = cleaned_data.get('y')
        group_by = cleaned_data.get('group_by')
        color = cleaned_data.get('color')

        if output_type == 'table' and not columns:
            raise ValidationError('Columns must be selected for table output type')
        elif output_type in ['scatter', 'line', 'bar']:
            if not x:
                raise ValidationError('X-axis must be selected for scatter, line or bar output type')
            if not y:
                raise ValidationError('Y-axis must be selected for scatter, line or bar output type')              

        elif output_type == 'pie':
            if not x:
                raise ValidationError('X-axis must be selected for pie output type')
            if not group_by:
                raise ValidationError('Group by must be selected for pie output type')
        elif output_type == 'histogram':
            if not x:
                raise ValidationError('X-axis must be selected for histogram output type')
        elif output_type == 'value':
            if not color:
                raise ValidationError('Color must be selected for value output type')

        return cleaned_data



class SqlQueryForm(forms.Form):
    code = forms.CharField(widget=forms.HiddenInput(), required=False)  # Hidden field to store code content

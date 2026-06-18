

from bloomerp.automation.base_executor import BaseExecutor
from bloomerp.automation.flows.if_condition import BranchStopped
from bloomerp.automation.schema import WorkflowInputRequirement, WorkflowValueType
from bloomerp.components.application_fields.filters import FILTERABLE_FIELD_TYPES
from bloomerp.field_types.lookups import Lookup
from bloomerp.forms.base_content_type_form import BaseContentTypeForm
from bloomerp.forms.base_workflow_node_form import BaseWorkflowNodeForm
from django import forms

from bloomerp.models.application_field import ApplicationField
from bloomerp.utils.filters import filter_model
from bloomerp.utils.models import get_model_and_content_type_or_404

class ObjectIfCondtionForm(BaseContentTypeForm):
    refresh_on_input = True
    
    field = forms.CharField(
        widget=forms.HiddenInput(),
        required=True,
    )
    lookup = forms.CharField(
        required=True,
        help_text="The lookup to perform on the field. For example, 'exact' or 'icontains'. You can also use double underscore notation to perform lookups on related fields, e.g. 'user__username__icontains'.",
        widget=forms.HiddenInput()
    )
    value = forms.CharField(
        required=True,
        help_text="The value to compare the field against. Can be a literal value or a reference to the input data using {{ }} notation, e.g. {{ input.username }}.",
        widget=forms.HiddenInput()
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Check which fields are set
        content_type_set = self.field_is_set("content_type_id")
        field_set = self.field_is_set("field")
        lookup_set = self.field_is_set("lookup")
        
        if content_type_set:
            content_type_id = self.initial.get("content_type_id") or self.data.get("content_type_id")
            self.fields["field"].widget = forms.Select(attrs={"class": "select w-full"}, choices=[
                (field.id, field.title) for field in ApplicationField.objects.filter(content_type_id=content_type_id, field_type__in=FILTERABLE_FIELD_TYPES)
            ])
        
        if content_type_set and field_set:
            field_id = self.initial.get("field") or self.data.get("field")
            application_field = _resolve_application_field(field_id, content_type_id)
            lookup_choices = application_field.field_type_enum.value.lookups
            self.fields["lookup"].widget = forms.Select(
                attrs={"class": "select w-full"}, 
                choices=[(lookup.value.id, lookup.value.display_name) for lookup in lookup_choices]
            )
            
        if content_type_set and field_set and lookup_set:
            # Get the lookup
            selected_lookup = None
            for lookup in lookup_choices:
                if lookup.value.id == (self.initial.get("lookup") or self.data.get("lookup")):
                    selected_lookup = lookup.value
                    break
                
            if selected_lookup:
                try:
                    self.fields["value"].widget = selected_lookup.widget_func(application_field)
                except Exception as e:
                    # If there's an error creating the widget, fall back to a simple text input
                    self.fields["value"].widget = forms.TextInput(attrs={"class": "input w-full"})
                

def _can_parse_to_int(value) -> bool:
    try:
        int(value)
        return True
    except ValueError:
        return False

def _resolve_application_field(field_value, content_type_id):
    if isinstance(field_value, str) and not _can_parse_to_int(field_value):
        return ApplicationField.objects.get(
            field=field_value,
            content_type_id=content_type_id
        )
    else:
        return ApplicationField.objects.get(id=field_value)
    
def _resolve_lookup(lookup_id:str, application_field:ApplicationField) -> Lookup:
    lookup_choices = application_field.field_type_enum.value.lookups
    for lookup in lookup_choices:
        if lookup.value.id == lookup_id:
            return lookup
    raise ValueError(f"Lookup with id {lookup_id} not found for field {application_field.field}")

def _resolve_lookup_allias(lookup_id:str, application_field:ApplicationField) -> str:
    # First try to resolve the lookup id directly
    lookup = _resolve_lookup(lookup_id, application_field).value
    if lookup.aliases:
        return lookup.aliases[0]
    
    return lookup.id
    

class ObjectIfConditionExecutor(BaseExecutor):
    config_form = ObjectIfCondtionForm
    input_requirement = WorkflowInputRequirement(
        value_type=WorkflowValueType.OBJECT,
        label="A database object",
        description="The incoming data is not used by this action.",
    )
    
    @classmethod
    def accepts_input_schema(cls, incoming_schema, config = None):
        is_object = incoming_schema.value_type == WorkflowValueType.OBJECT
        has_id_field = any(field.path == "id" for field in incoming_schema.fields)
        return is_object and has_id_field
    
    @classmethod
    def get_output_schema(cls, config = None, input_schema = None):
        return input_schema
    
    def execute(self, input_data: dict) -> bool:
        # Get the content type id
        params = self.resolve_config(input_data)
        
        # Get the content_type_id, field, lookup, and value
        content_type_id = params.get("content_type_id")
        field_id = params.get("field")
        lookup = params.get("lookup")
        value = params.get("value")
        # Get the content type id
        ModelCls, ct = get_model_and_content_type_or_404(content_type_id)

        # Resolve the application field if it's a string
        if isinstance(field_id, str) and not _can_parse_to_int(field_id):
            application_field = ApplicationField.objects.get(
                name=field_id,
                content_type_id=content_type_id
            )
        else:
            application_field = _resolve_application_field(field_id, content_type_id)
        
        # Resolve the lookup
        alias = _resolve_lookup_allias(lookup, application_field)
        
        # Build the filter kwargs
        if alias:
            filter = application_field.field + "__" + alias
        else:
            filter = application_field.field
        filter_kwargs = {
            filter: value
        }    
    
        # Check if any objects match the filter
        exists = filter_model(ModelCls, filter_kwargs, queryset=ModelCls.objects.filter(id=str(input_data.get("id")))).exists()
        if exists:
            return input_data
        return BranchStopped(f"No {ModelCls._meta.verbose_name} matches the condition {application_field.field} {alias} {value}")
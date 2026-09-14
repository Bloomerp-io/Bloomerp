from typing import Annotated, Any, Literal
from pydantic import (
    BaseModel,
    Field,
    field_serializer,
)
from bloomerp.lookups.definition import FilterFieldContext
from pydantic import ConfigDict, GetPydanticSchema
from pydantic_core import core_schema


class FilterField(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    
    field:str
    label:str
    # Internal metadata: validate the instance without treating its factories
    # and Django model references as part of the JSON input schema.
    context: Annotated[
        FilterFieldContext,
        GetPydanticSchema(lambda _type, _handler: core_schema.is_instance_schema(FilterFieldContext)),
    ]

    @field_serializer("context")
    def serialize_context(self, context: FilterFieldContext):
        return {
            "field_type": context.field_type.id,
            "application_field": (
                context.application_field.pk
                if context.application_field is not None
                else None
            ),
        }


class FilterFieldGroup(BaseModel):
    name : str
    fields : list[FilterField] = Field(default_factory=list)


class FilterCondition(BaseModel):
    field_path:str
    value:Any
    lookup_id:str
    

class Filter(BaseModel):
    connector : Literal["AND", "OR"]
    conditions: list[FilterCondition] = Field(default_factory=list)
    
    
Filters = list[Filter]
    


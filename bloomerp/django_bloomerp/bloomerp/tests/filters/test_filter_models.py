


from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.application_field import ApplicationField
from bloomerp.tests.base.core_test_case import BaseBloomerpTestCaseWithModels


class TestFilterModels(BaseBloomerpTestCaseWithModels):
    
    def test_serialize_filter(self):
        """
        UC: We want to be able to serialize a filter
        
        Expected Result: the filter is serialized properly
        """
        filter = Filter(
            connector="AND",
            conditions=[
                FilterCondition(
                    field_path="first_name",
                    value="David",
                    expression="eq"
                ),
                FilterCondition(
                    field_path="last_name",
                    value="Jacobs",
                    expression="equals"
                ),
            ]   
        )
        
        serialized = filter.model_dump()
        
        self.assertEqual(
            serialized,
            {
                "connector" : "AND",
                "conditions" : [
                    {
                        "field_path" : "first_name",
                        "value" : "David",
                        "expression" : "eq"
                    },
                    {
                        "field_path" : "last_name",
                        "value" : "Jacobs",
                        "expression" : "equals"
                    }
                ]
            }
        )
        
        
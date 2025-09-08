from bloomerp.datatypes.widgets import WidgetSchema
from bloomerp.constants.widgets import WidgetType
import pandas as pd

class WidgetGenerator:
    schema : WidgetSchema
    dataframe : pd.DataFrame
    
    def __init__(self, schema:WidgetSchema, dataframe:pd.DataFrame):
        self.schema = schema
        self.dataframe = dataframe
        
    def generate(self) -> dict:
        """Generates the rendering options for the widget."""
        if not self.schema.is_valid():
            pass
        
        if not self._is_valid_with_data():
            pass
        
        match self.schema.widget_type:
            case WidgetType.CHART:
                pass
            case WidgetType.TABLE:
                pass
            case WidgetType.KPI:
                pass
            case _:
                pass
        
        
    def _is_valid_with_data(self) -> bool:
        """Checks whether the columns are present in the data"""
    
    
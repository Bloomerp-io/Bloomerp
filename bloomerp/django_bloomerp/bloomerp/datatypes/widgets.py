from bloomerp.constants.widgets import ShelveType
from bloomerp.constants.widgets import WidgetType


class BaseShelve:
    id : str
    column : str
    options : dict
    shelve_type : ShelveType


class WidgetSchema:
    shelves : list[BaseShelve]
    widget_type : WidgetType
    name : str
    description : str
    options : dict

    
    @classmethod
    def from_dict(schema:dict) -> "WidgetSchema":
        """Creates a widget schema from a dictionary"""
        pass
    
    def to_dict(self) -> dict:
        """Serializes the widget schema object to a dictionary"""
        pass
    
    def is_valid(self) -> bool:
        match self.widget_type:
            case WidgetType.KPI:
                pass
            case WidgetType.CHART:
                pass
            case WidgetType.TABLE:
                pass
            case _:
                raise ValueError("Invalid widget type")
    
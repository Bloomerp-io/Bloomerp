


class DataviewMixin:
    """
    Mixin that renders the dataview
    """
    template_name = "mixins/dataview_mixin.html"
    
    filters = {}
    args = {}
    dataview_content_type_id : int = None
    
    def get_dataview_filters(self) -> dict:
        """
        Returns the filters for the dataview
        """
        return self.filters
    
    def get_dataview_args(self) -> dict:
        """
        Returns the arguments for the dataview
        """
        return self.args
    
    def get_dataview_content_type_id(self) -> int:
        """
        Returns the content type id for the dataview
        """
        return self.dataview_content_type_id
    
    
    def get_context_data(self, **kwargs):
        """
        Returns the context data for the dataview
        """
        ctx = super().get_context_data(**kwargs)
        ctx["dataview_filters"] = self.get_dataview_filters()
        ctx["dataview_args"] = self.get_dataview_args()
        ctx["dataview_content_type_id"] = self.get_dataview_content_type_id()
        return ctx
    
    
    
    
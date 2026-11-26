

from bloomerp.views.generic.detail.base import BaseBloomerpDetailView
from bloomerp.views.mixins.dataview_mixin import DataviewMixin


class OneToOneRelationshipView(BaseBloomerpDetailView):
    dataview_filter_shorthand = True
    model = None
    related_model = None 
    attribute_name = None
    relationship_field_name = None
    permission_field_name = None

    
    
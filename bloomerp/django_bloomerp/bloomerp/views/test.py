

from django.views.generic import TemplateView

from bloomerp.models.base_bloomerp_model import FieldLayout, LayoutItem, LayoutRow
from bloomerp.router import router
from bloomerp.views.mixins import HtmxMixin
from bloomerp.views.view_mixins.form import BloomerpLayoutFormMixin


@router.register(
    "test",
    "app"
)
class TestView(BloomerpLayoutFormMixin, HtmxMixin, TemplateView):
    
    def get_layout_object(self):
        return FieldLayout(
            rows=[
                LayoutRow(
                    columns=4,
                    items=[
                        LayoutItem(
                            id=62,
                            colspan=2
                        )
                    ]
                )
            ]
        )

    def can_change_layout(self) -> bool:
        return False
    
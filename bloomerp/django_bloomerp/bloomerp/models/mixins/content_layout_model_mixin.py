from django.db import models

from bloomerp.models.base_bloomerp_model import FieldLayout


class ContentLayoutModelMixin(models.Model):
    """
    Shared behavior for models that store a sectioned content layout.
    """
    class Meta:
        abstract = True

    layout = models.JSONField(default=dict, blank=True)

    @property
    def layout_obj(self) -> FieldLayout:
        from bloomerp.services.sectioned_layout_services import normalize_layout_payload

        if isinstance(self.layout, FieldLayout):
            return self.layout
        return normalize_layout_payload(self.layout)

    def validate_layout(self) -> None:
        from bloomerp.services.sectioned_layout_services import normalize_layout_payload

        normalize_layout_payload(self.layout)

    def set_layout(self, layout: FieldLayout | dict | None) -> None:
        from bloomerp.services.sectioned_layout_services import normalize_layout_payload

        self.layout = normalize_layout_payload(layout).model_dump()

from bloomerp.models.base_bloomerp_model import BloomerpModel, FieldLayout, LayoutItem, LayoutRow
from django.db import models

from bloomerp.models.definition import BloomerpModelConfig

class EmailAccount(BloomerpModel):
    class Meta:
        db_table = "bloomerp_email_account"
        verbose_name = "Email Account"
        verbose_name_plural = "Email Accounts"
    
    bloomerp_config = BloomerpModelConfig(
        module=None,
        layout=FieldLayout(
            rows=[
                LayoutRow(
                    columns=2,
                    items=[
                        LayoutItem(id="name"),
                        LayoutItem(id="email_address"),
                    ]
                )
            ]
        )    
    )
    
    name = models.CharField(
        max_length=255,
        blank=True,
    )
    email_address = models.EmailField(
        max_length=255,
        unique=True,
    )
        
    def save(self, *args, **kwargs):
        if not self.name:
            self.name = self.email_address
        super().save(*args, **kwargs)
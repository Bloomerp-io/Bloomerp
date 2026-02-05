from django.db import models


class Module(models.Model):
    """A module within a workspace."""
    name = models.CharField(
        max_length=255,
        
        )
    description = models.TextField(
        editable=False
    )
    
    def __str__(self):
        return f"{self.name}"
    
    
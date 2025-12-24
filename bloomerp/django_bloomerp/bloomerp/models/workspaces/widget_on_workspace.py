from django.db import models

class WidgetOnWorkspace(models.Model):
    workspace = models.ForeignKey(to="Workspace", on_delete=models.CASCADE)
    widget = models.ForeignKey(to="Widget", on_delete=models.CASCADE)
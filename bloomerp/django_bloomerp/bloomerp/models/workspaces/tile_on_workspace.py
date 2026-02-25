from django.db import models

class TileOnWorkspace(models.Model):
    workspace = models.ForeignKey(to="Workspace", on_delete=models.CASCADE)
    tile = models.ForeignKey(to="Tile", on_delete=models.CASCADE)
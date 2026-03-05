from django.db import models

class DataBaseConnection:
    """
    A model to store a database connection configuration for workspaces.
    This is used to connect to external databases which can be used
    in SQL queries for tiles on the workspace.
    """

    name = models.CharField(
        max_length=255
        )
    host = models.URLField(
        max_length=255
    )
    port = models.IntegerField()
    username = models.CharField(
        max_length=255
    )
    password = models.CharField(
        max_length=255
    )



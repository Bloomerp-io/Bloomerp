from django.db import models

class TodoLabel(models.Model):
    """
    Model representing a label that can be assigned to to-do items.
    """
    class Meta:
        managed = True
        db_table = 'bloomerp_todo_label'
    
    name = models.CharField(max_length=100)
    color = models.CharField(max_length=7)  # Hex color code

    def __str__(self):
        return self.name
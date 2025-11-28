from django.db import models
from bloomerp.models.fields import TextEditorField
from bloomerp.models import BloomerpModel
from django.conf import settings
from django.utils.translation import gettext as _
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.exceptions import ValidationError

class TodoPriority(models.TextChoices):
    URGENT = ('urgent', 'Urgent')
    HIGH = ('high', 'High')
    MEDIUM = ('medium','Medium')
    LOW = ('low', 'Low')
    
# TODO: Create effort model based on t-shirt sizing (check linear for this)
class TodoEffort(models.IntegerChoices):
    XS = (1, 'XS')
    S = (2, 'S')
    M = (4, 'M')
    L = (8, 'L')
    XL = (16, 'XL')

# TODO: Status should be based on what is defined in the overall bloomerp settings module
# TODO: Use status field for this one -> status field can be used later on in table views 
class TodoStatus(models.TextChoices):
    BACKLOG = ('backlog', 'Backlog')
    IN_PROGRESS = ('in_progress', 'In Progress')
    IN_REVIEW = ('in_review', 'In Review')
    COMPLETED = ('completed', 'Completed')
    CANCELLED = ('cancelled', 'Cancelled')
    DUPLICATE = ('duplicate', 'Duplicate')

class Todo(BloomerpModel):
    """
    The todo model is for Bloomerp's internal project management module.
    """
    class Meta(BloomerpModel.Meta):
        managed = True
        db_table = 'bloomerp_todo'

    avatar = None
    allow_string_search = False # Do not allow string search for todos (we dont want to-do's to be searchable in the search bar)
    string_search_fields = ['content'] # Allow string search for content

    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        null=True,
        blank=True,
        related_name='todos',
        )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        null=True, 
        blank=True, 
        on_delete=models.CASCADE, 
        related_name='requested_todos', 
        help_text=_("The user who requested the todo")
        )
    required_by = models.DateField(
        null=True, 
        blank=True,
        help_text=_("The date by which the todo is required")
        )
    priority = models.CharField(
        max_length=20,
        help_text=_("The priority of the todo"), 
        choices=TodoPriority.choices,
        default=TodoPriority.MEDIUM
        )
    effort = models.IntegerField(
        null=True, 
        blank=True,
        help_text=_("The effort required for the todo"),
        choices=TodoEffort.choices,
        default=TodoEffort.M
        )
    title = models.CharField(
        max_length=255, 
        help_text=_("The name of the todo")
        )
    content = TextEditorField(
        blank=True, 
        null=True
        )
    datetime_completed = models.DateTimeField(
        null=True, 
        blank=True
        )
    status = models.CharField(
        max_length=50, 
        choices=TodoStatus.choices,
        default=TodoStatus.BACKLOG
        )
    

    # For if the todo is related to a model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(max_length=36, null=True, blank=True) # In order to support both UUID and integer primary keys
    content_object = GenericForeignKey("content_type", "object_id")

    @property
    def content_safe(self):
        from django.utils.safestring import mark_safe
        return mark_safe(self.content)

    @property
    def is_completed(self) -> bool:
        """Returns whether the item has been completed or not

        Returns:
            bool: _description_
        """
        return self.status == TodoStatus.COMPLETED
    
    def __str__(self):
        return self.title

    def clean(self):
        errors = {}
        from django.utils import timezone
        from django.core.exceptions import ObjectDoesNotExist

        # Set the datetime completed to None if the todo is not completed
        if self.is_completed and not self.datetime_completed:
            self.datetime_completed = timezone.now()
        elif not self.is_completed:
            self.datetime_completed = None


        if self.content_type and self.object_id:
            try:
                self.content_object  # Triggers a lookup
            except ObjectDoesNotExist:
                errors['content_object'] = _("The related object does not exist")

        if errors:
            raise ValidationError(errors)

        return super().clean()

import uuid
from django.conf import settings
from bloomerp.models import BloomerpModel
from django.db import models

class AIConversation(BloomerpModel):
    class Meta:
        managed = True
        db_table = "bloomerp_ai_conversation"
        verbose_name = "AI conversation"
        verbose_name_plural = "AI conversations"

    CONVERSATION_TYPES = [
        ('sql', 'SQL'), 
        ('document_template', 'Document Template Generator'), 
        ('tiny_mce_content', 'TinyMCE Content Generator'), 
        ('bloom_ai', 'Bloom AI'),
        ('code', 'Code Generator'),
        ('object_bloom_ai', 'Object Bloom AI')
    ]

    avatar = None
    title = models.CharField(max_length=255, default='AI Conversation')
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation_history = models.JSONField(null=True, blank=True)
    conversation_type = models.CharField(max_length=20, choices=CONVERSATION_TYPES, default='bloom_ai')
    auto_named = models.BooleanField(default=False, help_text="Whether the conversation has been auto-named")
    args = models.JSONField(null=True, blank=True, help_text="Extra arguments for the conversation")

    allow_string_search = False
    string_search_fields = ['title']

    @property
    def number_of_messages(self):
        return len(self.conversation_history)
    
    def __str__(self):
        return self.title
    

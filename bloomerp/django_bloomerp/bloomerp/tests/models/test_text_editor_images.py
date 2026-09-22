"""Persistence checks for images in rich-text model fields."""

import base64
import tempfile

from django.test import TestCase, override_settings

from bloomerp.models.document_templates.document_template import DocumentTemplate
from bloomerp.models.files.file import File
from bloomerp.models.project_management.todo import Todo

IMAGE_BYTES = b"\x89PNG\r\n\x1a\n" + b"image payload"
INLINE_IMAGE = f'<p>Picture</p><img src="data:image/png;base64,{base64.b64encode(IMAGE_BYTES).decode()}" alt="Example">'


class TestTextEditorImages(TestCase):
    def test_todo_image_is_stored_reused_and_removed(self) -> None:
        """Use case: Save and edit a to-do containing an inline image.
        Expected result: One linked file replaces the payload and is deleted on removal.
        """
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            # 1. Save the editor HTML and check its file reference.
            todo = Todo.objects.create(title="Image example", content=INLINE_IMAGE)
            file = File.objects.get(object_id=str(todo.pk), meta__text_editor_field="content")
            todo.refresh_from_db()
            self.assertEqual(file.file.read(), IMAGE_BYTES)
            self.assertIn(f'/{file.url.lstrip("/")}', todo.content)
            self.assertNotIn("data:image", todo.content)

            # 2. Repeated autosaves of the same editor input reuse the file.
            todo.content = INLINE_IMAGE
            todo.save(update_fields=["content"])
            self.assertEqual(File.objects.filter(object_id=str(todo.pk)).count(), 1)

            # 3. Removing the image deletes its linked file.
            todo.content = "<p>Picture removed</p>"
            todo.save(update_fields=["content"])
            self.assertFalse(File.objects.filter(pk=file.pk).exists())

    def test_document_template_image_survives_updates(self) -> None:
        """Use case: Save an image through the document template editor.
        Expected result: The template retains a usable file reference on later saves.
        """
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            # 1. Create a template with an image and check its stored HTML.
            template = DocumentTemplate.objects.create(name="Image template", template=INLINE_IMAGE)
            file = File.objects.get(object_id=str(template.pk), meta__text_editor_field="template")
            template.refresh_from_db()
            self.assertIn(f'/{file.url.lstrip("/")}', template.template)
            self.assertNotIn("data:image", template.template)

            # 2. Browser serialization makes local image URLs absolute.
            template.template = template.template.replace(
                f'/{file.url.lstrip("/")}',
                f'http://testserver/{file.url.lstrip("/")}',
            ) + "<p>New text</p>"
            template.save(update_fields=["template"])
            template.refresh_from_db()
            self.assertIn(f'/{file.url.lstrip("/")}', template.template)
            self.assertTrue(File.objects.filter(pk=file.pk).exists())

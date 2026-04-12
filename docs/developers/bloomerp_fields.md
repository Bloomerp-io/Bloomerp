## Bloomerp Fields
The Bloomerp framework provides a set of custom fields that extend the default Django model fields, offering additional functionality and validation tailored for specific use cases.

### BloomerpFileField

**Description:**
`BloomerpFileField` is a custom ForeignKey field to the `File` model, with built-in validation for allowed file extensions. It ensures that only files with specified extensions can be associated with the model.

**Usage:**
Use `BloomerpFileField` when you need to associate files with your models and enforce specific file types.

**Example:**

```python
from bloomerp.models.fields import BloomerpFileField
from django.db import models

class Document(models.Model):
    title = models.CharField(max_length=255)
    file = BloomerpFileField(allowed_extensions=['.pdf', '.docx'])

# Creating a new Document with a validated file
document = Document.objects.create(title="Project Report", file=some_file_instance)
```

### CodeField

**Description:**
`CodeField` is a custom Django model field designed to store code snippets with syntax highlighting. It supports multiple programming languages and includes validation for syntax correctness.

**Usage:**
Use `CodeField` when you need to store and display code snippets within your models, ensuring they are syntactically correct.

**Example:**

```python
from bloomerp.models.fields import CodeField
from bloomerp.models import BloomerpModel

class DocumentTemplateStyling(BloomerpModel):
    name = models.CharField(max_length=100) 
    styling = CodeField(language='css', default='')
    
    def __str__(self):
        return self.name

# Creating a new Script with Python code
styling = DocumentTemplateStyling.objects.create(
    name="Hello World Script",
    styling="""
.hover:cursor-pointer {
    background-color:red;
}
"""
)
```

**Example UI:**

![Code field example](/docs/images/code_field_example.png)

### TextEditorField

**Description:**
`TextEditorField` is a custom Django model field that integrates a rich text editor widget. It allows for enhanced text editing capabilities, including formatting and media embedding.

**Usage:**
Use `TextEditorField` when you need rich text input in your models, such as for blog posts, descriptions, or content management.

**Example:**

```python
from bloomerp.models.fields import TextEditorField
from bloomerp.models import BloomerpModel

class Insight(BloomerpModel):
    title = models.CharField(max_length=255)
    content = TextEditorField()

    def __str__(self):
        return self.title

# Creating a new Insight with rich text content
insight = Insight.objects.create(
    title="My First Blog Post",
    content="<h1>Welcome!</h1><p>This is my first post.</p>"
)
```

**Example UI:**

![Text editor field example](/docs/images/text_editor_field_example.png)

# Additional Information

- **Validation:** Each custom field includes validation to ensure data integrity. For example, `BloomerpFileField` validates file extensions, and `CodeField` can validate syntax based on the specified language.
- **Widgets:** Custom form widgets are integrated with these fields to provide enhanced user interfaces in Django admin and forms.
- **Serialization:** Fields like `ListField` handle the serialization and deserialization of complex data types seamlessly.

# Conclusion

The Bloomerp custom fields extend Django's capabilities, providing specialized functionalities tailored for business management applications. By leveraging these fields, developers can create more robust and feature-rich models with ease.

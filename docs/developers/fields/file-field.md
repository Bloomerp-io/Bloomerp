# File Reference

`BloomerpFileField` is a virtual Django field backed by `FileFieldReference`.
It adds no column to the parent table and uses a plain file input. Reading
`object.field_name` returns a list of `File` records, including for single-file
fields (zero or one record).

Each reference contains a unique `file_id`, an `object_id` supporting integer
and UUID primary keys, and an `application_field_id`. The application field's
content type identifies the parent model. An index on
`(application_field_id, object_id)` supports field reads and collection pages.
One file has one owning reference. Field-owned files leave `File.content_type`
and `File.object_id` empty; those columns remain available for generic object
uploads and generated documents. Files use the owner's object folder.

| Option | Default | Behavior |
| --- | --- | --- |
| `multiple` | `False` | Allow more than one attachment. |
| `allowed_extensions` | `"__all__"` | Case-insensitive extensions; an empty list accepts all. |
| `max_files` | `None` | Maximum combined count of retained and new files. |
| `max_file_size` | `None` | Maximum bytes per new upload. |
| `blank` | `True` | Allow an empty attachment field. |

The widget and validation never write files. `BloomerpModelForm.save()` saves
the parent and then its structured attachment values in a database transaction.
With `save(commit=False)`, save the parent first and call
`save_structured_fields()`. Uploading a replacement into a single-file field
removes its old attachment. Multiple-file editors provide **Keep** controls;
uncheck a control to remove that file when saving.

For programmatic edits, call the model field's
`on_save(parent, retained_ids, uploaded_files)` after saving the parent. This
validates upload limits and reference ownership, serializes edits on the parent,
stores new files, and deletes removed references and files. Direct assignment
is unsupported. Unrelated model saves leave the references intact.

Deleting a parent, application field, or reference deletes its owned files and
stored bytes. Deleting a `File` cascades its reference. Moving a field-owned
file to another object's generic files removes its former reference while
preserving the moved file. Like other generic relations, `object_id` has no
SQL foreign key to the parent; parent cleanup runs through Django's deletion
signals. Raw SQL deletion bypasses that lifecycle.

The field registry exposes `batch_value_loader`. Dataviews call only the generic
`prepare_field_values(objects, fields)` hook. The file type loads the displayed
fields in one reference query joined to `File`, caches records on each parent,
and renders escaped file links without additional field-value queries. Fields
hidden by row-level field-access annotations do not populate the display cache.
Direct reads outside that preparation load the requested field lazily.

The field reuses the existing `IS_NULL` lookup and Boolean editor through a
`BoundLookup`. `is_null=true` matches objects with no references for that field;
`is_null=false` matches objects with at least one reference. The query adapter
uses a scoped `EXISTS` subquery, so multiple files do not duplicate parent rows
and generic object uploads do not affect the result. SQL filtering compiles
virtual fields through the same query adapter, and Python evaluation checks
whether the file collection is empty.

The file browser explicitly joins references, application fields, and content
types, then loads parent objects once per model. Its links include the field
label, use HTMX navigation to `#field_name`, and reuse object preview tooltips.
Visibility and actions follow the owning field's permissions; generic uploads
use the `files` field. The detail frame focuses the target input after navigation.

`File.metadata` returns the Pydantic model declared in
`bloomerp.models.files.file`. Document-template provenance uses
`metadata.document_template` (`id`, `name`); bulk-import drafts use
`metadata.bulk_upload` (`content_type_id`, `model_label`, `original_filename`).
PDF signature provenance uses `metadata.signature` (`signed`, `user_id`,
`signed_file_id`) and preserves the document template on source and signed files.
`File.save()` and `full_clean()` validate metadata. Migration
`0077_file_field_references` creates the shared table and converts historical
flat provenance into this nested structure, with a reverse conversion.
Adding an Employee resume declaration therefore requires no parent-table
migration or per-field relation table.

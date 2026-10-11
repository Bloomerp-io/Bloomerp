# File references

`BloomerpFileField` is a virtual Django field backed by `FileReference` and
`FileNode`. It adds no column to the parent table. Reading `object.field_name`
returns a list of file nodes, including for single-file fields (zero or one node).

A file node owns immutable stored content and cached metadata. A reference stores
its `file_id`, parent `content_type_id` and `object_id`, and optional
`application_field_id`. An editor image additionally has an `occurrence_id`.
The index on `(content_type_id, object_id, application_field_id)` supports
field reads. Multiple records and fields can share the same file node.

| Option | Default | Behavior |
| --- | --- | --- |
| `multiple` | `False` | Allow more than one attachment. |
| `allowed_extensions` | `"__all__"` | Case-insensitive extensions; an empty list accepts all. |
| `max_files` | `None` | Maximum combined count of retained and new files. |
| `max_file_size` | `None` | Maximum bytes per new upload. |
| `blank` | `True` | Allow an empty attachment field. |

The widget and validation never write files. `BloomerpModelForm.save()` saves
the parent and its structured attachment values in a database transaction.
With `save(commit=False)`, save the parent first and call
`save_structured_fields()`.

For programmatic edits, call the model field's
`on_save(parent, retained_ids, uploaded_files)` after saving the parent. It
validates limits and reference ownership, serializes edits on the parent,
stores new file nodes, and removes discarded references. Replacing an attachment
does not delete its file node or bytes. Direct assignment is unsupported.

Deleting a parent, application field, or reference removes its references while
preserving shared file nodes. Referenced nodes cannot be deleted. Deleting an
unused node schedules storage cleanup after commit; the key remains if another
node uses it. Rollback discards the cleanup callback. Raw SQL deletion bypasses
the Django lifecycle.

The field registry's `batch_value_loader` joins references to file nodes and
caches field values on displayed parent objects. Row-level field visibility
controls which fields enter that cache. Direct reads load the field lazily.
`is_null` lookups use scoped `EXISTS` subqueries, so multiple attachments do not
duplicate parent rows and generic object attachments do not affect field lookups.

`FileAccessManager.get_queryset(queryset)` filters readable file nodes before
pagination. A referenced file requires one readable owner field; an embedded
comment attachment follows its parent's `comments` field. Unreferenced uploads
require their uploader or global library view access. Bulk-import sources remain
private wizard state. Mutations require access to every affected reference.

File-browser virtual folders derive from references. Physical folders are
`FileNode` records with `kind="FOLDER"`; moving a node changes its physical
`parent`, not its references. Generated legacy object-folder hierarchies and
legacy folder-management endpoints are retired.

`FileNode.metadata` returns `FileNodeMetaData` from `bloomerp.files.definition`.
It includes size, MIME type, extension, original filename, bulk-import identity,
and optional document-template and PDF-signature provenance. Generated PDFs
reference their template and source records. Signing creates a separate node
and records its identity on the original node.

Migration `0086_file_nodes_and_object_references` copies legacy files and usages
without copying bytes or the old generated folder hierarchy. Migration
`0087_retire_legacy_file_models` verifies the storage-key cutover and removes
`File`, `FileFolder`, `FileFieldReference`, and template folder destinations.
Historical model definitions remain in migration state only.

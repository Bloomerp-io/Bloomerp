"""Typed, queryable metadata captured for immutable file-node content."""

from pydantic import BaseModel, ConfigDict, Field


class BulkUploadFileMetadata(BaseModel):
    """Identify the model and original filename of a temporary bulk-import source."""

    model_config = ConfigDict(extra="forbid")
    content_type_id: int = Field(gt=0)
    model_label: str
    original_filename: str


class FileNodeMetaData(BaseModel):
    """Cache file facts without requiring storage access when listing or filtering."""

    # Preserve legacy provenance until its domain-specific migration is implemented.
    model_config = ConfigDict(extra="allow")

    size: int | None = Field(
        default=None,
        ge=0,
        strict=True,
        description="Content size in bytes; unknown for unavailable legacy content, never a folder total.",
    )
    original_filename: str | None = Field(
        default=None,
        description="Upload filename, or storage-key basename when importing an existing file.",
    )
    extension: str | None = Field(
        default=None,
        description="Lowercase filename extension without the dot; empty for extensionless files.",
    )
    mime_type: str | None = Field(
        default=None,
        description="Filename-derived MIME hint, not a security-verified content type.",
    )
    content_encoding: str | None = Field(
        default=None, description="Filename-derived compression encoding, such as gzip."
    )

    bulk_upload: BulkUploadFileMetadata | None = None

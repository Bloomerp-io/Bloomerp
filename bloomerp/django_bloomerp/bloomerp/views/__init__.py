"""Public base and standard Bloomerp views for application developers."""

from importlib import import_module
from typing import Any

_EXPORTS = {
    "BaseBloomerpView": "base",
    "BaseBloomerpDetailView": "generic.detail.base",
    "BloomerpBulkUploadView": "generic.model.bulk_upload",
    "BloomerpCreateView": "generic.model.create",
    "BloomerpDeleteView": "generic.detail.delete",
    "BloomerpDetailOverviewView": "generic.detail.overview",
    "BloomerpDetailFileListView": "generic.detail.files",
    "BloomerpFileListView": "generic.model.file_list",
    "BloomerpListView": "generic.model.list",
    "ForeignRelationshipView": "generic.detail.foreign_relationship",
}


def __getattr__(name: str) -> Any:
    """Import a standard view only when an application requests it."""
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f"{__name__}.{_EXPORTS[name]}"), name)


__all__ = [
    "BaseBloomerpDetailView",
    "BaseBloomerpView",
    "BloomerpBulkUploadView",
    "BloomerpCreateView",
    "BloomerpDeleteView",
    "BloomerpDetailFileListView",
    "BloomerpDetailOverviewView",
    "BloomerpFileListView",
    "BloomerpListView",
    "ForeignRelationshipView",
]

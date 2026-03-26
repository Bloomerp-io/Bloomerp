from bloomerp.router import router
from .base_detail import BloomerpBaseDetailView
from .list_view import BloomerpListView
from .create_view import BloomerpCreateView
from .detail_files import BloomerpDetailFileListView
from .bulk_upload import BloomerpBulkUploadView
from .file_list import BloomerpFileListView
from .detail_comments import BloomerpDetailCommentsView
from .bookmarks import BloomerpBookmarksView

__all__ = [
    "router",
    "BloomerpBaseDetailView",
    "BloomerpListView",
    "BloomerpCreateView",
    "BloomerpDetailFileListView",
    "BloomerpBulkUploadView",
    "BloomerpFileListView",
    "BloomerpDetailCommentsView",
    "BloomerpBookmarksView",
]

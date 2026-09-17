from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer
from bloomerp.models.files.file import File
from bloomerp.models.files.file_folder import FileFolder
from bloomerp.utils.models import string_search_on_qs


class TestFileBrowserRenderer(TestCase):
    def setUp(self):
        self.request_factory = RequestFactory()
        self.file_content_type = ContentType.objects.get_for_model(File)

    def _state(self, *, request, queryset, model=File, content_type=None):
        content_type = content_type or self.file_content_type
        return SimpleNamespace(
            request=request,
            queryset=queryset,
            model=model,
            content_type=content_type,
            content_type_id=content_type.pk,
            options=SimpleNamespace(related_fields={}),
            filters=[],
        )

    @patch(
        "bloomerp.services.file_permission_services.user_can_view_folder",
        return_value=True,
    )
    @patch(
        "bloomerp.services.file_permission_services.user_can_view_file",
        return_value=True,
    )
    def test_nested_folder_preserves_file_search(self, _can_view_file, _can_view_folder):
        folder = FileFolder.objects.create(name="Nested")
        matching = File.objects.create(
            name="Needle document",
            file="needle.txt",
            folder=folder,
            persisted=True,
        )
        File.objects.create(
            name="Unrelated document",
            file="other.txt",
            folder=folder,
            persisted=True,
        )
        request = self.request_factory.get("/files/", {"q": "Needle"})
        queryset = string_search_on_qs(File.objects.all(), "Needle")
        renderer = FileBrowserRenderer(
            self._state(request=request, queryset=queryset)
        )

        _current_folder, _folders, files = renderer._get_file_model_items(folder)

        self.assertEqual([file.pk for file in files], [matching.pk])

    @patch(
        "bloomerp.services.file_permission_services.user_can_view_folder",
        return_value=False,
    )
    @patch(
        "bloomerp.services.file_permission_services.user_can_view_file",
        return_value=False,
    )
    def test_related_model_items_exclude_inaccessible_files(
        self,
        _can_view_file,
        _can_view_folder,
    ):
        host = FileFolder.objects.create(name="Host")
        host_content_type = ContentType.objects.get_for_model(FileFolder)
        inaccessible = File(
            name="Private document",
            file="private.txt",
            content_type=host_content_type,
            object_id=str(host.pk),
            persisted=True,
        )
        File.objects.bulk_create([inaccessible])
        request = self.request_factory.get("/folders/")
        renderer = FileBrowserRenderer(
            self._state(
                request=request,
                queryset=FileFolder.objects.filter(pk=host.pk),
                model=FileFolder,
                content_type=host_content_type,
            )
        )

        _folders, files = renderer._get_related_model_items(None)

        self.assertEqual(files, [])

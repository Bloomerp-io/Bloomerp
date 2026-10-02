from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.contenttypes.models import ContentType
from django.test import RequestFactory, TestCase

from bloomerp.dataviews.file_browser.renderer import FileBrowserRenderer
from bloomerp.filters.definition import Filter, FilterCondition
from bloomerp.models.files.file import File
from bloomerp.models.files.file_folder import FileFolder
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object
from bloomerp.utils.models import string_search_on_qs


class TestFileBrowserRenderer(TestCase):
    @patch(
        "bloomerp.services.file_permission_services.user_can_view_folder",
        return_value=True,
    )
    @patch(
        "bloomerp.services.file_permission_services.user_can_view_file",
        return_value=True,
    )
    def test_object_folder_combines_distinct_queries(
        self, _can_view_file: MagicMock, _can_view_folder: MagicMock
    ) -> None:
        """
        Use case: An object's protected folder includes files of configured relations.
        Expected result: Both distinct and non-distinct inputs preserve search and scope.
        """
        # 1. Attach files to a host, a related object, and an unrelated object.
        host = FileFolder.objects.create(name="Host")
        related = FileFolder.objects.create(name="Related", parent=host)
        unrelated = FileFolder.objects.create(name="Unrelated")
        content_type = ContentType.objects.get_for_model(FileFolder)
        host_folder = ensure_folder_hierarchy_for_object(host)
        host_file = File.objects.create(
            name="Needle host", file="host.txt", content_object=host, persisted=True
        )
        related_file = File.objects.create(
            name="Needle related",
            file="related.txt",
            content_object=related,
            persisted=True,
        )
        File.objects.create(
            name="Other related",
            file="other.txt",
            content_object=related,
            persisted=True,
        )
        File.objects.create(
            name="Needle unrelated",
            file="unrelated.txt",
            content_object=unrelated,
            persisted=True,
        )
        request = self.request_factory.get("/files/", {"q": "Needle"})

        # 2. Exercise both input query shapes with and without related scopes.
        for distinct in (False, True):
            for include_related in (False, True):
                with self.subTest(distinct=distinct, include_related=include_related):
                    queryset = string_search_on_qs(
                        File.objects.filter(
                            content_type=content_type, object_id=str(host.pk)
                        ),
                        "Needle",
                    )
                    if distinct:
                        queryset = queryset.distinct()
                    state = self._state(request=request, queryset=queryset)
                    state.filters = [
                        Filter(
                            connector="AND",
                            conditions=[
                                FilterCondition(
                                    field_path="content_type",
                                    lookup_id="equals",
                                    value=content_type.pk,
                                ),
                                FilterCondition(
                                    field_path="object_id",
                                    lookup_id="equals",
                                    value=str(host.pk),
                                ),
                            ],
                        )
                    ]
                    state.options.related_fields = {
                        content_type.pk: ["filefolder"] if include_related else []
                    }
                    current_folder, _folders, files = FileBrowserRenderer(
                        state
                    )._get_file_model_items(host_folder)

                    # 3. Verify matching files appear once within the selected scope.
                    self.assertEqual(current_folder, host_folder)
                    expected = [host_file.pk]
                    if include_related:
                        expected.append(related_file.pk)
                    self.assertCountEqual([file.pk for file in files], expected)

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

import re
from unittest.mock import patch

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models
from django.urls import reverse

from bloomerp.components.files.browser import _get_folder_display_name
from bloomerp.models.files.file import File
from bloomerp.models.files.file_folder import FileFolder
from bloomerp.modules.misc import MiscModule
from bloomerp.tests.base import (
    BaseBloomerpTestCaseWithModels,
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class FileTestFixtureMixin:
    auto_create_customers = False
    create_foreign_models = True

    def get_object(self):
        return self.CustomerModel.objects.first()

    def create_file(
        self,
        obj: models.Model | None = None,
        user=None,
        file_name="test_file.txt",
        content=b"Test content",
    ):
        return File.objects.create(
            name=file_name,
            file=ContentFile(content, name=file_name),
            content_type=ContentType.objects.get_for_model(obj) if obj else None,
            object_id=obj.pk if obj else None,
            created_by=user,
            updated_by=user,
        )


class TestFilesComponent(FileTestFixtureMixin, BloomerpComponentTestCase):
    """Tests single-request behavior of the file-browser component."""

    view_name = "components_files"

    def get_test_scenarios(self) -> list[RequestScenario]:
        return [
            RequestScenario(
                name="render default file dataview",
                user=self.admin_user,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text(
                            'bloomerp-component="file-dataview-container"'
                        ),
                        self.contains_text('id="data-view-data-section"'),
                        self.contains_text('bloomerp-component="datatable"'),
                    ]
                ),
            ),
            RequestScenario(
                name="render folders before dataview",
                user=self.admin_user,
                prepare=self._prepare_root_folder,
                expected=ExpectedResult(
                    response_validators=self._folders_precede_dataview,
                ),
            ),
            RequestScenario(
                name="render file model actions",
                user=self.admin_user,
                prepare=self._prepare_persisted_file,
                expected=ExpectedResult(
                    response_validators=self._file_actions_are_rendered,
                ),
            ),
            RequestScenario(
                name="render generated model folder",
                user=self.admin_user,
                prepare=self._prepare_model_folder,
                expected=ExpectedResult(
                    response_validators=self._contains_customer_model_name,
                ),
            ),
            RequestScenario(
                name="search all hierarchy levels from root",
                user=self.admin_user,
                query_params={"q": "unique"},
                prepare=self._prepare_root_search,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("unique_file_name.txt"),
                        self.contains_text("unique_folder_name"),
                        self.does_not_contain_text("qwertyujnjkhsda"),
                    ]
                ),
            ),
            RequestScenario(
                name="render search target partial",
                user=self.admin_user,
                query_params={"q": "unique"},
                headers={
                    "HX-Request": "true",
                    "HX-Target": "data-view-data-section",
                },
                prepare=self._prepare_search_file,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("unique_file_name.txt"),
                        self.does_not_contain_text('id="data-view-data-section"'),
                        self.does_not_contain_text(
                            'bloomerp-component="file-dataview-container"'
                        ),
                        self.does_not_contain_text('id="data-view-search-input-'),
                    ]
                ),
            ),
            RequestScenario(
                name="render root breadcrumb",
                user=self.admin_user,
                expected=ExpectedResult(
                    response_validators=self._current_breadcrumb("Root"),
                ),
            ),
            RequestScenario(
                name="search only below current folder",
                user=self.admin_user,
                prepare=self._prepare_nested_search,
                expected=ExpectedResult(
                    response_validators=[
                        self.does_not_contain_text("unique_file_name_root.txt"),
                        self.contains_text("unique_file_name_last_folder.txt"),
                        self.contains_text("folder_unique_folder_name"),
                    ]
                ),
            ),
            RequestScenario(
                name="show folder ancestry",
                user=self.admin_user,
                prepare=self._prepare_folder_hierarchy,
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text("Cool folder"),
                        self.contains_text("Another folder"),
                        self.contains_text("The coolest folder"),
                    ]
                ),
            ),
            RequestScenario(
                name="hide folder ancestry",
                user=self.admin_user,
                prepare=self._prepare_hidden_folder_hierarchy,
                expected=ExpectedResult(
                    response_validators=[
                        self.does_not_contain_text("Cool folder"),
                        self.does_not_contain_text("Another folder"),
                        self.contains_text("The coolest folder"),
                    ]
                ),
            ),
            RequestScenario(
                name="omit navigation folder from active filters",
                user=self.admin_user,
                prepare=self._prepare_navigation_folder,
                expected=ExpectedResult(
                    response_validators=self._navigation_filter_is_hidden,
                ),
            ),
            RequestScenario(
                name="use dynamic object folder name",
                user=self.admin_user,
                prepare=self._prepare_dynamic_object_name,
                expected=ExpectedResult(
                    response_validators=self.contains_text("Halle Lujah"),
                ),
            ),
            RequestScenario(
                name="keep explicit scoped-folder name",
                user=self.admin_user,
                prepare=self._prepare_custom_folder,
                expected=ExpectedResult(
                    response_validators=self._current_breadcrumb("Payslips"),
                ),
            ),
            RequestScenario(
                name="use object as hidden-ancestor breadcrumb root",
                user=self.admin_user,
                prepare=self._prepare_object_root,
                expected=ExpectedResult(
                    response_validators=self._object_root_is_rendered,
                ),
            ),
            RequestScenario(
                name="use custom folder below object breadcrumb root",
                user=self.admin_user,
                prepare=self._prepare_custom_object_breadcrumb,
                expected=ExpectedResult(
                    response_validators=self._custom_object_root_is_rendered,
                ),
            ),
            RequestScenario(
                name="preserve object breadcrumb root in folder link",
                user=self.admin_user,
                prepare=self._prepare_custom_object_root,
                expected=ExpectedResult(
                    response_validators=self._object_root_link_is_preserved,
                ),
            ),
            RequestScenario(
                name="render custom object-folder partial without dataview shell",
                user=self.admin_user,
                headers={
                    "HX-Request": "true",
                    "HX-Target": "data-view-data-section",
                },
                prepare=self._prepare_custom_object_breadcrumb,
                expected=ExpectedResult(
                    response_validators=[
                        self._custom_object_root_is_rendered,
                        self.does_not_contain_text(
                            'bloomerp-component="file-dataview-container"'
                        ),
                    ],
                ),
            ),
            RequestScenario(
                name="render object-root partial without dataview shell",
                user=self.admin_user,
                headers={
                    "HX-Request": "true",
                    "HX-Target": "#data-view-data-section",
                },
                prepare=self._prepare_object_root,
                expected=ExpectedResult(
                    response_validators=[
                        self._current_object_breadcrumb,
                        self.does_not_contain_text('id="data-view-data-section"'),
                        self.does_not_contain_text(
                            'bloomerp-component="file-dataview-container"'
                        ),
                    ]
                ),
            ),
            RequestScenario(
                name="avoid duplicate current object breadcrumb",
                user=self.admin_user,
                prepare=self._prepare_visible_object_root,
                expected=ExpectedResult(
                    response_validators=self._current_object_breadcrumb,
                ),
            ),
            RequestScenario(
                name="render folder with stale content type",
                user=self.admin_user,
                prepare=self._prepare_stale_content_type,
                expected=ExpectedResult(
                    response_validators=self.contains_text("Orphaned folder"),
                ),
            ),
        ]

    @staticmethod
    def _set_query(setup: RequestScenario, **params) -> None:
        setup.query_params = params

    def _prepare_root_folder(self, _setup: RequestScenario) -> None:
        FileFolder.objects.create(
            name="Contracts",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

    def _prepare_persisted_file(self, _setup: RequestScenario) -> None:
        self.rendered_file = self.create_file(
            user=self.admin_user,
            file_name="contract.txt",
        )
        self.rendered_file.persisted = True
        self.rendered_file.save(update_fields=["persisted"])

    def _prepare_model_folder(self, setup: RequestScenario) -> None:
        self.create_file(obj=self.get_object(), user=self.admin_user)
        module_folder = FileFolder.objects.filter(name=MiscModule.name).first()
        self._set_query(setup, folder=module_folder.id)

    def _prepare_root_search(self, _setup: RequestScenario) -> None:
        self.create_file(
            obj=self.get_object(),
            user=self.admin_user,
            file_name="unique_file_name.txt",
        )
        parent = FileFolder.objects.create(
            name="qwertyujnjkhsda",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        FileFolder.objects.create(
            name="unique_folder_name",
            parent=parent,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

    def _prepare_search_file(self, _setup: RequestScenario) -> None:
        self.create_file(
            obj=self.get_object(),
            user=self.admin_user,
            file_name="unique_file_name.txt",
        )

    def _prepare_nested_search(self, setup: RequestScenario) -> None:
        parent = FileFolder.objects.create(
            name="folder_HSDLFJHASDLFDSA",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        child = FileFolder.objects.create(
            name="folder_unique_folder_name",
            parent=parent,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        self.create_file(user=self.admin_user, file_name="unique_file_name_root.txt")
        nested_file = self.create_file(
            user=self.admin_user,
            file_name="unique_file_name_last_folder.txt",
        )
        nested_file.folder = child
        nested_file.save(update_fields=["folder"])
        self._set_query(setup, folder=parent.id, q="unique")

    def _create_folder_hierarchy(self):
        parent = None
        folders = []
        for name in ("Cool folder", "Another folder", "The coolest folder"):
            parent = FileFolder.objects.create(
                name=name,
                parent=parent,
                created_by=self.admin_user,
                updated_by=self.admin_user,
            )
            folders.append(parent)
        return folders

    def _prepare_folder_hierarchy(self, setup: RequestScenario) -> None:
        folders = self._create_folder_hierarchy()
        self._set_query(setup, folder=folders[-1].id)

    def _prepare_hidden_folder_hierarchy(self, setup: RequestScenario) -> None:
        folders = self._create_folder_hierarchy()
        self._set_query(
            setup,
            folder=folders[-1].id,
            hide_ancestor_folders="true",
        )

    def _prepare_navigation_folder(self, setup: RequestScenario) -> None:
        self.navigation_folder = FileFolder.objects.create(
            name="Cool folder",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        self._set_query(setup, folder=self.navigation_folder.id)

    def _prepare_dynamic_object_name(self, setup: RequestScenario) -> None:
        obj = self.get_object()
        file = self.create_file(obj=obj, user=self.admin_user)
        obj.first_name = "Halle"
        obj.last_name = "Lujah"
        obj.save()
        self._set_query(setup, folder=file.folder.parent.id)

    def _create_custom_object_folder(self):
        self.current_object = self.get_object()
        file = self.create_file(obj=self.current_object, user=self.admin_user)
        custom_folder = FileFolder.objects.create(
            name="Payslips",
            parent=file.folder,
            content_type=file.folder.content_type,
            object_id=file.folder.object_id,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        return file.folder, custom_folder

    def _prepare_custom_folder(self, setup: RequestScenario) -> None:
        _object_folder, custom_folder = self._create_custom_object_folder()
        self._set_query(setup, folder=custom_folder.id)

    def _prepare_object_root(self, setup: RequestScenario) -> None:
        self.current_object = self.get_object()
        file = self.create_file(obj=self.current_object, user=self.admin_user)
        self._set_query(
            setup,
            folder=file.folder.id,
            hide_ancestor_folders="true",
        )

    def _prepare_visible_object_root(self, setup: RequestScenario) -> None:
        self.current_object = self.get_object()
        file = self.create_file(obj=self.current_object, user=self.admin_user)
        self._set_query(setup, folder=file.folder.id)

    def _prepare_custom_object_root(self, setup: RequestScenario) -> None:
        self.object_folder, self.custom_folder = self._create_custom_object_folder()
        self._set_query(
            setup,
            folder=self.object_folder.id,
            hide_ancestor_folders="true",
        )

    def _prepare_custom_object_breadcrumb(self, setup: RequestScenario) -> None:
        self.object_folder, self.custom_folder = self._create_custom_object_folder()
        self._set_query(
            setup,
            folder=self.custom_folder.id,
            hide_ancestor_folders="true",
        )

    def _prepare_stale_content_type(self, setup: RequestScenario) -> None:
        stale_content_type = ContentType.objects.create(
            app_label="missing_app",
            model="missingmodel",
        )
        folder = FileFolder.objects.create(
            name="Orphaned folder",
            content_type=stale_content_type,
            object_id="123",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        self._set_query(setup, folder=folder.id)

    def _folders_precede_dataview(self, response) -> bool:
        content = response.content.decode("utf-8")
        return (
            "Contracts" in content
            and content.index("data-file-browser-folders")
            < content.index('bloomerp-component="datatable"')
        )

    def _file_actions_are_rendered(self, response) -> bool:
        content = response.content.decode("utf-8")
        file_content_type = ContentType.objects.get_for_model(File)
        expected_urls = [
            reverse(
                "components_objects_actions",
                kwargs={
                    "content_type_id": file_content_type.pk,
                    "object_id": self.rendered_file.pk,
                    "action_id": "view_file",
                },
            ),
            *[
                reverse(
                    f"components_files_{action}",
                    kwargs={"file_id": self.rendered_file.pk},
                )
                for action in ("rename", "move", "delete")
            ],
        ]
        return all(url in content for url in expected_urls) and (
            f'data-rename-file="{self.rendered_file.pk}"' not in content
        )

    def _contains_customer_model_name(self, response) -> bool:
        return str(self.CustomerModel._meta.verbose_name_plural) in response.content.decode()

    def _current_breadcrumb(self, label: str, count: int = 1):
        def validator(response):
            matches = re.findall(
                rf'aria-current="page"[^>]*>\s*{re.escape(label)}\s*</a>',
                response.content.decode("utf-8"),
            )
            return len(matches) == count

        return self._named_validator(f"current_breadcrumb({label!r})", validator)

    def _current_object_breadcrumb(self, response) -> bool:
        return self._current_breadcrumb(str(self.current_object))(response)

    def _navigation_filter_is_hidden(self, response) -> bool:
        content = response.content.decode()
        return (
            f"Folder is {self.navigation_folder.id}" not in content
            and f"Folder is {self.navigation_folder.name}" not in content
        )

    def _object_root_is_rendered(self, response) -> bool:
        content = response.content.decode()
        return (
            'data-open-root="true"' not in content
            and "Location" not in content
            and self._current_object_breadcrumb(response)
        )

    def _custom_object_root_is_rendered(self, response) -> bool:
        content = response.content.decode()
        return (
            content.count(str(self.current_object)) == 1
            and self._current_breadcrumb("Payslips")(response)
            and "Root" not in content
        )

    def _object_root_link_is_preserved(self, response) -> bool:
        expected = (
            "hide_ancestor_folders=true&amp;folder_id="
            f"{self.custom_folder.id}"
        )
        return expected in response.content.decode()


class TestFileRelatedComponentWorkflows(
    FileTestFixtureMixin,
    BaseBloomerpTestCaseWithModels,
):
    """Tests multi-endpoint file workflows that do not fit one request setup."""

    def test_file_object_action_redirects_to_file_url(self):
        file = self.create_file(user=self.admin_user, file_name="contract.txt")
        file.persisted = True
        file.save(update_fields=["persisted"])
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse(
                "components_objects_actions",
                kwargs={
                    "content_type_id": ContentType.objects.get_for_model(File).pk,
                    "object_id": file.pk,
                    "action_id": "view_file",
                },
            )
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.headers["HX-Redirect"], file.url)

    def test_file_modal_actions_support_get_and_post(self):
        file = self.create_file(user=self.admin_user, file_name="contract.txt")
        file.persisted = True
        file.save(update_fields=["persisted"])
        destination = FileFolder.objects.create(
            name="Archive",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )
        self.client.force_login(self.admin_user)

        rename_url = reverse("components_files_rename", kwargs={"file_id": file.pk})
        self.assertContains(self.client.get(rename_url), "contract.txt")
        self.client.post(rename_url, {"name": "renamed.txt"})
        file.refresh_from_db()
        self.assertEqual(file.name, "renamed.txt")

        move_url = reverse("components_files_move", kwargs={"file_id": file.pk})
        self.assertContains(self.client.get(move_url), "Archive")
        self.client.post(move_url, {"target_folder": destination.pk})
        file.refresh_from_db()
        self.assertEqual(file.folder, destination)

        delete_url = reverse("components_files_delete", kwargs={"file_id": file.pk})
        self.assertContains(self.client.get(delete_url), "renamed.txt")
        self.client.post(delete_url)
        self.assertFalse(File.objects.filter(pk=file.pk).exists())

    def test_file_actions_deny_user_without_permissions(self):
        file = self.create_file(user=self.admin_user, file_name="private.txt")
        file.persisted = True
        file.save(update_fields=["persisted"])
        self.client.force_login(self.normal_user)

        view_response = self.client.post(
            reverse(
                "components_objects_actions",
                kwargs={
                    "content_type_id": ContentType.objects.get_for_model(File).pk,
                    "object_id": file.pk,
                    "action_id": "view_file",
                },
            )
        )
        self.assertEqual(view_response.status_code, 403)
        for action in ("rename", "move", "delete"):
            with self.subTest(action=action):
                response = self.client.get(
                    reverse(
                        f"components_files_{action}",
                        kwargs={"file_id": file.pk},
                    )
                )
                self.assertEqual(response.status_code, 403)

    def test_generated_module_folder_name_is_localized_at_display_time(self):
        self.create_file(obj=self.get_object(), user=self.admin_user)
        module_folder = FileFolder.objects.get(
            name=MiscModule.name,
            parent__isnull=True,
        )

        with patch(
            "bloomerp.modules.definition.pgettext",
            side_effect=lambda _context, message: (
                "Diversos" if message == "Miscellaneous" else message
            ),
        ):
            self.assertEqual(_get_folder_display_name(module_folder), "Diversos")

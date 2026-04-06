

from ast import mod

from django.urls import reverse
from urllib.parse import urlencode

from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models.files.file import File
from bloomerp.models.files.file_folder import FileFolder
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.modules.misc import MiscModule

class TestFilesComponent(BaseBloomerpModelTestCase):
    auto_create_customers = False
    create_foreign_models = True
    url_name = "components_files"

    def get_object(self):
        return self.CustomerModel.objects.first()

    def create_file(self, obj:models.Model=None, user=None, file_name="test_file.txt", content=b"Test content"):
        # 1. Create the file content
        file_content = ContentFile(content, name=file_name)

        attrs = {
            "name": file_name,
            "file": file_content,
            "content_type": ContentType.objects.get_for_model(obj) if obj else None,
            "object_id": obj.pk if obj else None,
            "created_by": user,
            "updated_by": user
        }

        return File.objects.create(**attrs)
            
    def get_url(self, obj:models.Model=None, **params):
        url = reverse(self.url_name)
        query_params = {}
        if obj:
            query_params.update({
                "content_type": ContentType.objects.get_for_model(obj).id,
                "object_id": obj.pk,
            })
        query_params.update({key: value for key, value in params.items() if value is not None})
        if query_params:
            url += f"?{urlencode(query_params)}"
        return url

    def assert_current_breadcrumb(self, response, label: str, count: int = 1):
        self.assertContains(
            response.content,
            f'<span class="inline-flex items-center text-sm font-medium text-gray-400" aria-current="page">{label}</span>',
            html=True,
            count=count,
        )
    
    def test_creating_file_with_object_creates_model_level_folder_under_module_folder(self):
        """
        This test checks whether creating a file will automatically create folders that
        go back to the model level under the module folder
        """
        module_name = MiscModule().name
        model_name = self.CustomerModel._meta.verbose_name_plural # i.e. "Customers"

        # 1. Get an object
        obj = self.get_object()

        # 2. Create a file associated with the object
        self.create_file(
            obj=obj,
            user=self.admin_user
        )

        # 3. Make a request to the files component
        module_level_folder = FileFolder.objects.filter(
            name=module_name,
        ).first()

        # 4, Construct url
        self.client.force_login(self.admin_user)
        url = self.get_url(folder=module_level_folder.id)

        # 5. Check that the response contains the model name as a folder in it's markup
        response = self.client.get(url)
        self.assertContains(response.content, model_name)

    def test_searching_for_file_returns_files_and_folders_from_all_levels_of_hierarchy_if_from_root(self):
        """
        This test checks whether searching for a file in the files
        will return results that match the search query from all levels of the file/folder hierarchy (i.e. file, model-level folder, module-level folder)
        """
        # 1. Get an object
        obj = self.get_object()

        # 2. Create a file associated with the object
        file = self.create_file(
            obj=obj,
            user=self.admin_user,
            file_name="unique_file_name.txt"
        )

        # 3. Create two folders
        random_string = "qwertyujnjkhsda"
        folder_1 = FileFolder.objects.create(
            name=random_string,
            created_by=self.admin_user,
            updated_by=self.admin_user
        )
        folder_2 = FileFolder.objects.create(
            name="unique_folder_name",
            created_by=self.admin_user,
            updated_by=self.admin_user,
            parent=folder_1
        )

        # 3. Get the root url for the files component, and add a query param to search for the file name
        self.client.force_login(self.admin_user)
        url = self.get_url(q="unique")

        response = self.client.get(url)

        # 4. Check that the response contains the file name
        self.assertContains(response.content, "unique_file_name.txt")
        self.assertContains(response.content, "unique_folder_name")
        self.assertNotContains(response.content, random_string)

    def test_search_target_returns_only_file_browser_data_section(self):
        self.create_file(
            obj=self.get_object(),
            user=self.admin_user,
            file_name="unique_file_name.txt",
        )

        render_id = "files-test-render"
        self.client.force_login(self.admin_user)
        response = self.client.get(
            self.get_url(q="unique", _render_id=render_id),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET=f"file-browser-data-section-{render_id}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response.content, f'id="file-browser-data-section-{render_id}"', html=False)
        self.assertContains(response.content, "unique_file_name.txt")
        self.assertNotContains(response.content, f'id="file-browser-{render_id}"', html=False)
        self.assertNotContains(response.content, 'data-search-input', html=False)

    def test_root_view_shows_root_breadcrumb(self):
        """
        This test checks whether the root view of the files component
        shows a breadcrumb with the label "Root
        """
        self.client.force_login(self.admin_user)
        response = self.client.get(self.get_url())

        self.assert_current_breadcrumb(response, "Root")

    def test_searching_for_file_returns_files_and_folders_from_only_current_folder_if_not_from_root(self):
        """
        This test checks whether searching for a file in the files component
        will return results that match the search query only from the current folder if not from root
        """
        # 1. Create two folders
        folders = []
        for i in ["HSDLFJHASDLFDSA", "unique_folder_name"]:
            folder = FileFolder.objects.create(
                name=f"folder_{i}",
                created_by=self.admin_user,
                updated_by=self.admin_user,
                parent=folders[-1] if folders else None
            )
            folders.append(folder)

        parent_folder = folders[0]

        # 2. Create a file in the root and last folder with unique names
        root_file_name = "unique_file_name_root.txt"
        root_file = File.objects.create(
            name=root_file_name,
            file=ContentFile(b"Test content", name=root_file_name),
            created_by=self.admin_user,
            updated_by=self.admin_user
        )

        last_folder_file_name = "unique_file_name_last_folder.txt"
        last_folder_file = File.objects.create(
            name=last_folder_file_name,
            file=ContentFile(b"Test content", name=last_folder_file_name),
            created_by=self.admin_user,
            updated_by=self.admin_user,
            folder=folders[-1]
        )

        # 3. Create a query using the id of the first folder
        self.client.force_login(self.admin_user)
        url = self.get_url(folder=folders[0].id, q="unique")

        # 4. Check that the response does not contain the root file, but contains the file in the last folder since it's a descendant of the first folder
        response = self.client.get(url)
        self.assertNotContains(response.content, root_file_name)
        self.assertContains(response.content, last_folder_file_name)
        self.assertContains(response.content, folders[-1].name)

    def test_filtering_by_folder_should_show_folder_hierarchy_unless_hide_ancestor_folders_param(self):
        """
        This test checks whether the folder hierarchy is visible
        when filtering by folder id in the files component.

        Filtering by folder id is the way to navigate through the folder hierarchy,
        so it's important that the folder hierarchy is visible when doing this.
        """
        # 1. Create three folders
        parent_folder = None
        folders:list[FileFolder] = []
        for i in ["Cool folder", "Another folder", "The coolest folder"]:
            folder = FileFolder.objects.create(
                name=i,
                created_by=self.admin_user,
                updated_by=self.admin_user,
                parent=parent_folder
            )
            parent_folder = folder
            folders.append(folder)

        # 2. Get the url for the files component, and add a query param to filter by the id of the first folder
        last_folder = folders[-1]
        url = self.get_url(folder=last_folder.id)

        # 3. Check that the response contains the names of all three folders, showing the hierarchy
        self.client.force_login(self.admin_user)
        response = self.client.get(url)

        for folder in folders:
            self.assertContains(response.content, folder.name)

        # 4. Now add a query param to hide ancestor folders, and check that only the last folder is visible
        url = self.get_url(folder=last_folder.id, hide_ancestor_folders="true")
        response = self.client.get(url)

        for folder in folders[:-1]:
            self.assertNotContains(response.content, folder.name)

    def test_filtering_by_folder_should_not_show_up_as_a_filtered_value(self):
        """
        For UI/UX purposes, when filtering by folder in the files component,
        the filter, being <span>Folder is [id]</span> should not show up in the
        response.
        """
        
        # 1. Create a folder
        folder = FileFolder.objects.create(
            name="Cool folder",
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        # 2. Get the url for the files component, and add a query param to filter by the id of the folder
        self.client.force_login(self.admin_user)
        url = self.get_url(folder=folder.id)

        # 3. Check that the response does not contain the text "Folder is [id]"
        response = self.client.get(url)
        self.assertNotContains(response.content, f"Folder is {folder.id}")
        self.assertNotContains(response.content, f"Folder is {folder.name}")

    def test_content_type_and_object_folders_use_dynamic_naming(self):
        """
        This test checks whether the folders that are automatically created for files that are associated with a content type and object use dynamic naming that reflects the name of the content type and object, rather than static names like "Model level folder" or "Object level folder"
        """
        # 1. Get an object
        obj : File = self.get_object()

        # 2. Create a file associated with the object
        file = self.create_file(
            obj=obj,
            user=self.admin_user
        )
        folder = file.folder.parent # i.e. the model level folder which contains the object level folder

        # 3. Change the name of the object, and check whether the name of the folder
        # (within the component) also changes
        original_folder_name = folder.name
        obj.first_name = "Halle"
        obj.last_name = "Lujah"

        obj.save()

        # Get the url for the files component filtered to the object
        url = self.get_url(folder=folder.id)
        self.client.force_login(self.admin_user)
        response = self.client.get(url)

        self.assertContains(response.content, "Halle Lujah")

    def test_custom_scoped_folder_keeps_explicit_name(self):
        obj = self.get_object()
        file = self.create_file(
            obj=obj,
            user=self.admin_user,
        )
        custom_folder = FileFolder.objects.create(
            name="Payslips",
            parent=file.folder,
            content_type=file.folder.content_type,
            object_id=file.folder.object_id,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(self.get_url(folder=custom_folder.id))

        self.assert_current_breadcrumb(response, "Payslips")

    def test_hide_ancestor_folders_hides_root_and_duplicate_object_breadcrumbs(self):
        obj = self.get_object()
        file = self.create_file(
            obj=obj,
            user=self.admin_user,
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(self.get_url(folder=file.folder.id, hide_ancestor_folders="true"))

        self.assertNotContains(response.content, 'data-open-root="true"', html=False)
        self.assertNotContains(response.content, "Location")
        self.assert_current_breadcrumb(response, str(obj))

    def test_hide_ancestor_folders_uses_object_folder_as_breadcrumb_root(self):
        obj = self.get_object()
        file = self.create_file(
            obj=obj,
            user=self.admin_user,
        )
        custom_folder = FileFolder.objects.create(
            name="Payslips",
            parent=file.folder,
            content_type=file.folder.content_type,
            object_id=file.folder.object_id,
            created_by=self.admin_user,
            updated_by=self.admin_user,
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(
            self.get_url(folder=custom_folder.id, hide_ancestor_folders="true")
        )

        self.assertContains(response.content, str(obj), count=1)
        self.assert_current_breadcrumb(response, "Payslips")
        self.assertNotContains(response.content, "Root")

    def test_object_breadcrumb_is_not_duplicated_when_current_folder_matches_object(self):
        obj = self.get_object()
        file = self.create_file(
            obj=obj,
            user=self.admin_user,
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(self.get_url(folder=file.folder.id))

        self.assert_current_breadcrumb(response, str(obj))

    def test_folder_with_stale_content_type_does_not_crash_component(self):
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

        self.client.force_login(self.admin_user)
        response = self.client.get(self.get_url(folder=folder.id))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response.content, "Orphaned folder")

class TestFilesUploadComponent(BaseBloomerpModelTestCase):
    auto_create_customers = False
    create_foreign_models = True
    url_name = "components_files_upload"

    def get_object(self):
        return self.CustomerModel.objects.first()
    
    def test_POST_uploads_a_file(self):
        """
        This tests whether making a post request to the files
        upload component actually creates a file in the database.
        """
        # 0. Check whether there are no files and init vars
        self.assertFalse(File.objects.exists())
        file_name = "test_file.txt"

        # 1. Get the url
        url = reverse(self.url_name)

        # 2. Create a file associated with the object via a POST request to the component
        self.client.force_login(self.admin_user)
        file_content = SimpleUploadedFile(file_name, b"Test content")
        response = self.client.post(url, {"files": file_content})
        self.assertEqual(response.status_code, 200)

        # 3. Check that the file was created in the database with the correct attributes
        file_qs = File.objects.filter(
            name=file_name,
        )
        self.assertTrue(file_qs.exists())

    def test_POST_with_content_type_and_object_uploads_a_file_associated_with_object(self):
        """
        This tests whether making a post request to the files
        upload component with content type and object id query params
        creates a file in the database that is associated with the correct content type and object.
        """
        # 0. Check whether there are no files and init vars
        self.assertFalse(File.objects.exists())
        file_name = "test_file.txt"

        # 1. Get an object and the url with content type and object id query params
        obj = self.get_object()
        url = reverse(self.url_name)
        

        # 2. Create a file associated with the object via a POST request to the component
        self.client.force_login(self.admin_user)
        file_content = SimpleUploadedFile(file_name, b"Test content")
        form_data = {
            "content_type_id": ContentType.objects.get_for_model(obj).id,
            "object_id": obj.pk,
            "files": file_content
        }

        response = self.client.post(url, form_data)
        self.assertEqual(response.status_code, 200)

        # 3. Check that the file was created in the database with the correct attributes, including being associated with the correct content type and object
        file_qs = File.objects.filter(
            name=file_name,
            content_type=ContentType.objects.get_for_model(obj),
            object_id=obj.pk
        )
        self.assertTrue(file_qs.exists())



        
        

        
    

    

        
        
        
        

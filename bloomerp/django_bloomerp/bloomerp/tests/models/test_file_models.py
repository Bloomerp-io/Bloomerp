
from bloomerp.tests.base import BaseBloomerpTestCaseWithModels
from bloomerp.models.files.file import File
from bloomerp.models.files.file_folder import FileFolder
from django.core.files.base import ContentFile
from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.modules.misc import MiscModule
from bloomerp.services.file_services import ensure_folder_hierarchy_for_object

class TestFileModels(BaseBloomerpTestCaseWithModels):
    auto_create_customers = True
    create_foreign_models = False

    def get_customer(self):
        return self.CustomerModel.objects.first()

    def create_file(
            self,
            obj:models.Model=None,
            user=None,
            content_type=None,
            file_name="test_file.txt",
            content=b"Test content"
        ):
        # 1. Create the file content
        file_content = ContentFile(content, name=file_name)

        attrs = {
            "name": file_name,
            "file": file_content,
            "content_type": content_type if content_type else (ContentType.objects.get_for_model(obj) if obj else None),
            "object_id": obj.pk if obj else None,
            "created_by": user,
            "updated_by": user
        }

        return File.objects.create(**attrs)
    
    def test_creating_file_without_object_does_not_create_folder(self):
        """
        This test checks whether creating a file without an associated object does not create any folders
        """
        # 1. Create a file without an associated object
        self.create_file(
            obj=None,
            user=self.admin_user
        )

        # 2. Check that no folders were created
        self.assertFalse(FileFolder.objects.exists())

    def test_creating_file_with_object_creates_folders_back_to_module_level(self):
        """
        This test checks whether creating a file will automatically create folders that
        go back to the module level
        """
        module_name = MiscModule().name

        # 0. Check that no folders exist at the start of the test
        self.assertFalse(FileFolder.objects.exists())

        # 1. Get a customer object
        customer = self.get_customer()

        # 2. Create a file associated with the customer
        self.create_file(
            obj=customer,
            user=self.admin_user
        )

        # 3. Check whether folders were created
        object_folder = FileFolder.objects.filter(name=str(customer)).first()
        model_folder = FileFolder.objects.filter(
            
        ).first()
        module_folder = FileFolder.objects.filter(name=module_name).first()

        # 4. Check that the object folder has the correct content type and object id
        self.assertIsNotNone(object_folder)
        self.assertEqual(object_folder.content_type, ContentType.objects.get_for_model(customer))
        self.assertEqual(object_folder.object_id, str(customer.pk))

        # 5. Check that the model folder has the correct content type and no object id
        self.assertIsNotNone(model_folder)
        self.assertEqual(model_folder.content_type, ContentType.objects.get_for_model(customer))
        self.assertIsNone(model_folder.object_id)

        # 6. Check that the module folder has no content type and no object id
        self.assertIsNotNone(module_folder)
        self.assertIsNone(module_folder.content_type)
        self.assertIsNone(module_folder.object_id)

        # 7. Check that all of those folders are protected, since they're automatically created for files
        for folder in [object_folder, model_folder, module_folder]:
            self.assertTrue(folder.protected)

    def test_generated_model_folder_identity_does_not_depend_on_display_name(self):
        customer = self.get_customer()
        content_type = ContentType.objects.get_for_model(customer)
        existing_folder = FileFolder.objects.create(
            name="Previously translated customers",
            content_type=content_type,
            protected=True,
        )

        ensure_folder_hierarchy_for_object(customer)

        model_folders = FileFolder.objects.filter(
            content_type=content_type,
            object_id__isnull=True,
        )
        self.assertEqual(model_folders.count(), 1)
        self.assertEqual(model_folders.get(), existing_folder)


from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.models.files.file import File
from bloomerp.models.files.file_folder import FileFolder
from django.core.files.base import ContentFile
from django.db import models
from django.contrib.contenttypes.models import ContentType
from bloomerp.modules.misc import MiscModule

class TestFileModels(BaseBloomerpModelTestCase):
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

    def test_folder_cannot_have_object_id_without_content_type(self):
        """
        This test checks that a folder cannot be created with an object id but no content type
        """
        # 1. Try to create a folder with an object id but no content type
        with self.assertRaises(Exception):
            FileFolder.objects.create(name=None, object_id=1)

    def test_child_folder_must_inherit_content_type_and_object_id_from_parent(self):
        """
        This test checks that a child folder cannot 
        be created with a different content type or object id than its parent.
        """
        # 1. Create a parent folder with a content type and object id
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        obj = self.get_customer()
        parent_folder = FileFolder.objects.create(name="Parent Folder", content_type=content_type, object_id=obj.pk)

        # 2. Try to create a child folder with a different content type
        with self.assertRaises(Exception):
            FileFolder.objects.create(name="Child Folder 1", parent=parent_folder, content_type=ContentType.objects.get_for_model(File), object_id=obj.pk)

        # 3. Try to create a child folder with a different object id
        with self.assertRaises(Exception):
            FileFolder.objects.create(name="Child Folder 2", parent=parent_folder, object_id=obj.pk + 1, content_type=content_type)

        # 4. Create a child folder with the same content type and object id
        child_folder = FileFolder.objects.create(name="Child Folder 3", parent=parent_folder, content_type=content_type, object_id=obj.pk)

        # 5. Check that the child folder was created successfully
        self.assertIsNotNone(child_folder)        

    

    

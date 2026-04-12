from django.test import TestCase, RequestFactory
from django.urls import reverse
from bloomerp.models import AbstractBloomerpUser, Bookmark, ContentType, File, BloomerpModel, Link
from bloomerp.components.bookmark import bookmark
from bloomerp.components.objects.bulk_update_objects import bulk_update_objects
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.middleware import MessageMiddleware
from django.contrib.sessions.middleware import SessionMiddleware
from bloomerp.components.bulk_upload_table import bulk_upload_table
from django.db import models
from django.apps import apps
from django.db import connection
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from bloomerp.components.files import files
from bloomerp.models import FileFolder


class BookmarkComponentTests(TestCase):
    def setUp(self):
        self.url = reverse('components_bookmark')
        self.factory = RequestFactory()
        self.user = AbstractBloomerpUser.objects.create_user(username='testuser', password='12345')
        self.content_type = ContentType.objects.create(app_label='test_app', model='testmodel')

    def test_bookmark_creation(self):
        request = self.factory.post(self.url, {
            'content_type_id': self.content_type.id,
            'object_id': 1
        }, content_type='application/json')
        request.user = self.user
        response = bookmark(request)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Bookmark.objects.filter(user=self.user, content_type=self.content_type, object_id=1).exists())

    def test_bookmark_deletion(self):
        Bookmark.objects.create(user=self.user, content_type=self.content_type, object_id=1)
        request = self.factory.post(self.url, {
            'content_type_id': self.content_type.id,
            'object_id': 1
        }, content_type='application/json')
        request.user = self.user
        response = bookmark(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Bookmark.objects.filter(user=self.user, content_type=self.content_type, object_id=1).exists())

    def test_bookmark_view_permission_denied(self):
        request = self.factory.get(self.url, {
            'content_type_id': self.content_type.id,
            'object_id': 1
        })
        request.user = self.user
        response = bookmark(request)
        self.assertEqual(response.status_code, 403)

    def test_bookmark_invalid_request(self):
        request = self.factory.post(self.url, {
            'content_type_id': 'invalid',
            'object_id': 'invalid'
        }, content_type='application/json')
        request.user = self.user
        response = bookmark(request)
        self.assertEqual(response.status_code, 400)

    def test_bookmark_unauthenticated(self):
        request = self.factory.post(self.url, {
            'content_type_id': self.content_type.id,
            'object_id': 1
        }, content_type='application/json')
        request.user = AnonymousUser()
        response = bookmark(request)
        self.assertEqual(response.status_code, 401)

# ----------------------------
# BULK UPDATE OBJECTS COMPONENT TESTS
# ----------------------------
class BulkUpdateObjectsTests(TestCase):
    def setUp(self):
        self.url = reverse('components_bulk_update_objects')
        self.factory = RequestFactory()
        self.user = AbstractBloomerpUser.objects.create_user(username='testuser', password='12345', is_superuser=True)
        self.content_type = ContentType.objects.get_for_model(File)
        self.file1 = File.objects.create(name='file1')
        self.file2 = File.objects.create(name='file2')
        self.message_middleware = MessageMiddleware(lambda request: None)
        self.session_middleware = SessionMiddleware(lambda request: None)

    def _add_middleware(self, request):
        self.session_middleware.process_request(request)
        request.session.save()
        self.message_middleware.process_request(request)

    def test_bulk_update_objects_success(self):
        request = self.factory.post(self.url+f'?content_type_id={self.content_type.id}&form_prefix=new_name', {
            'object_ids': [self.file1.id, self.file2.id],
        })
        request.user = self.user
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 200)
        self.file1.refresh_from_db()
        self.file2.refresh_from_db()
        self.assertEqual(self.file1.name, 'new_name')
        self.assertEqual(self.file2.name, 'new_name')

    def test_bulk_delete_objects_success(self):
        request = self.factory.post(self.url+f'?content_type_id={self.content_type.id}&form_prefix=new_name', {
            'content_type_id': self.content_type.id,
            'object_ids': [self.file1.id, self.file2.id],
            'delete_objects': 'true'
        })
        request.user = self.user
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(File.objects.filter(id__in=[self.file1.id, self.file2.id]).exists())

    def test_bulk_update_objects_permission_denied(self):
        self.user.user_permissions.clear()
        request = self.factory.post(self.url+f'?content_type_id={self.content_type.id}&form_prefix=new_name', {
            'content_type_id': self.content_type.id,
            'object_ids': [self.file1.id, self.file2.id],
            'form_prefix_name': 'new_name'
        })
        request.user = self.user
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 403)

    def test_bulk_delete_objects_permission_denied(self):
        self.user.user_permissions.clear()
        request = self.factory.post(self.url+f'?content_type_id={self.content_type.id}&form_prefix=new_name', {
            'content_type_id': self.content_type.id,
            'object_ids': [self.file1.id, self.file2.id],
            'delete_objects': 'true'
        })
        request.user = self.user
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 403)

    def test_bulk_update_objects_invalid_form_prefix(self):
        request = self.factory.post(self.url+f'?content_type_id={self.content_type.id}&form_prefix=new_name', {
            'content_type_id': self.content_type.id,
            'object_ids': [self.file1.id, self.file2.id]
        })
        request.user = self.user
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 400)

    def test_bulk_update_objects_invalid_content_type(self):
        request = self.factory.post(self.url+f'?content_type_id=invalid&form_prefix=new_name', {
            'content_type_id': 'invalid',
            'object_ids': [self.file1.id, self.file2.id],
            'form_prefix_name': 'new_name'
        })
        request.user = self.user
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 400)

    def test_bulk_update_objects_unauthenticated(self):
        request = self.factory.post(self.url+f'?content_type_id={self.content_type.id}&form_prefix=new_name', {
            'content_type_id': self.content_type.id,
            'object_ids': [self.file1.id, self.file2.id],
            'form_prefix_name': 'new_name'
        })
        request.user = AnonymousUser()
        self._add_middleware(request)
        response = bulk_update_objects(request)
        self.assertEqual(response.status_code, 401)

# ----------------------------
# BULK UPLOAD TABLE COMPONENT TESTS
# ----------------------------
class TestBulkUploadTableComponent(TestCase):
    # Create test model
    class A(models.Model):
        name = models.CharField(max_length=255)
        age = models.IntegerField()

        def __str__(self):
            return self.name
        
    # Create model that inherits from BloomerpModel
    class B(BloomerpModel):
        name = models.CharField(max_length=255)
        age = models.IntegerField()

        def __str__(self):
            return self.name

    def setUp(self):
        # Component URL
        self.url = reverse('components_bulk_upload_table')

        # Create users
        self.superuser = AbstractBloomerpUser.objects.create_user(username='testuser', password='12345', is_superuser=True)
        self.user = AbstractBloomerpUser.objects.create_user(username='testuser2', password='12345')
        
        # Create request factory
        self.factory = RequestFactory()

        # Get content type for model A and B
        self.content_type_a = ContentType.objects.get_for_model(self.A)
        self.content_type_b = ContentType.objects.get_for_model(self.B)

        # Save content types to database
        self.content_type_a.save()
        self.content_type_b.save()
        self.valid_file = SimpleUploadedFile("temp.csv", b'name,age\ntest,20\n', content_type="text/csv")
        self.invalid_file = SimpleUploadedFile("invalid.csv", b'invalid content', content_type="text/csv")


    def test_authorization_failed(self):
        '''Tests that the component only allows users with the correct permissions to access it'''
        # Create request with normal user
        request_1 = self.factory.post(
            self.url,
            data = {
                'bulk_upload_content_type_id': self.content_type_a.pk
            }
            )
        request_1.user = self.user

        # Test that normal user gets 403
        response_1 = bulk_upload_table(request_1)
        self.assertEqual(response_1.status_code, 403)

    def test_invalid_content_type(self):
        '''Tests that the component only allows valid content types'''
        # Create request with superuser
        request_2 = self.factory.post(
            self.url,
            data = {
                'bulk_upload_file': 'test',
                'bulk_upload_content_type_id': 'invalid'
            }
            )
        
        request_2.user = self.superuser

        # Test that superuser gets 400
        response_2 = bulk_upload_table(request_2)
        self.assertEqual(response_2.status_code, 400)

    def test_invalid_file(self):
        '''Tests that the component only allows valid files'''
        # Create request with superuser
        request = self.factory.post(
            self.url,
            data = {
                'bulk_upload_content_type_id': self.content_type_a.pk,
                'bulk_upload_file': SimpleUploadedFile("invalid.csv", b'invalid content', content_type="text/csv")
            },
            format='multipart'
        )
        request.user = self.superuser

        # Test that superuser
        response = bulk_upload_table(request)
        self.assertEqual(response.content.startswith(b'Error importing file:'), True)

    def test_valid_file(self):
        '''Tests that the component only allows valid files'''
        # Create request with superuser
        request = self.factory.post(
            self.url,
            data = {
                'bulk_upload_content_type_id': self.content_type_a.pk,
                'bulk_upload_file': self.valid_file
            },
            format='multipart'
        )
        request.user = self.superuser

        # Test that superuser
        response = bulk_upload_table(request)
        self.assertEqual(response.status_code, 200)

    def test_valid_form_submission(self):
        '''Tests that the component will create objects from a valid form submission'''
        # Create formset
        from django.forms.models import modelformset_factory

        data = [
            {'name': 'test1', 'age': 20},
            {'name': 'test2', 'age': 30},
            {'name': 'test3', 'age': 40}
        ]


        Formset = modelformset_factory(self.A, fields=['name', 'age'], extra=len(data))

        formset = Formset(queryset=self.A.objects.none(), initial=data, prefix = 'bulk_upload')

        # Create request with superuser
        request = self.factory.post(
            self.url,
            data = {
                'bulk_upload_content_type_id': self.content_type_a.pk,
                'bulk_upload_fields': ['name', 'age']
            },
        )
        request.user = self.superuser

        # Test that superuser
        response = bulk_upload_table(request)
        self.assertEqual(response.status_code, 200)

# ----------------------------
# SEARCH RESULTS COMPONENT TESTS
# ----------------------------
from bloomerp.components.global_search import search_results
class TestSearchResultsComponent(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = AbstractBloomerpUser.objects.create_user(username='testuser', password='12345', is_superuser=True)
        self.content_type = ContentType.objects.create(app_label='test_app', model='testmodel')
        Link.objects.create(name='Test Link', url='test/url', level='LIST', content_type=self.content_type)
        self.url = reverse('components_search_results')


    def test_no_query_provided(self):
        request = self.factory.get(self.url)
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'No query provided', response.content)

    def test_list_level_links(self):
        request = self.factory.get(self.url, {'search_results_query': '/testmodel'})
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Test Link', response.content)

    def test_app_level_links(self):
        Link.objects.create(name='App Link', url='app/url', level='APP')
        request = self.factory.get(self.url, {'search_results_query': '//A'})
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'App Link', response.content)

    def test_model_string_search(self):
        # Assuming your model has a string_search method
        request = self.factory.get(self.url, {'search_results_query': 'test'})
        request.user = self.user
        response = search_results(request)
        self.assertEqual(response.status_code, 200)
        # Add more assertions based on your model's string_search results

# ----------------------------
# FILES COMPONENT TESTS
# ----------------------------
class TestFilesComponent(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.url = reverse('components_files')
        
        # Create users
        self.user = AbstractBloomerpUser.objects.create_user(
            username='testuser', 
            password='12345'
        )
        self.superuser = AbstractBloomerpUser.objects.create_user(
            username='superuser', 
            password='12345',
            is_superuser=True
        )

        # Create test content type
        self.content_type = ContentType.objects.create(
            app_label='test_app',
            model='testmodel'
        )

        # Create test files
        self.file1 = File.objects.create(
            name='test_file1',
            content_type=self.content_type,
            object_id=1
        )
        self.file2 = File.objects.create(
            name='test_file2',
            content_type=self.content_type,
            object_id=2
        )

        # Create test folders
        self.folder1 = FileFolder.objects.create(
            name='test_folder1'
        )
        self.folder2 = FileFolder.objects.create(
            name='test_folder2',
            parent=self.folder1
        )

        # Add file to folder
        self.folder1.files.add(self.file1)

    def test_files_permission_denied(self):
        """Test that users without permission cannot view files"""
        request = self.factory.get(self.url)
        request.user = self.user
        response = files(request)
        self.assertEqual(response.content, b'User does not have permission to view files')

    def test_files_basic_listing(self):
        """Test basic file listing for authorized user"""
        self.user.user_permissions.add(
            ContentType.objects.get_for_model(File).permission_set.get(codename='view_file').id
        )
        request = self.factory.get(self.url)
        request.user = self.user
        request.htmx = type('HTMX', (), {'target': None})()
        response = files(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'test_file2', response.content)  # Only file2 should be visible (not in folder)

    def test_files_folder_filtering(self):
        """Test filtering files by folder"""
        self.user.user_permissions.add(
            ContentType.objects.get_for_model(File).permission_set.get(codename='view_file').id
        )
        request = self.factory.get(f'{self.url}?folder_id={self.folder1.id}')
        request.user = self.user
        request.htmx = type('HTMX', (), {'target': None})()
        response = files(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'test_file1', response.content)
        self.assertIn(b'test_folder2', response.content)

    def test_files_search(self):
        """Test searching files by name"""
        self.user.user_permissions.add(
            ContentType.objects.get_for_model(File).permission_set.get(codename='view_file').id
        )
        request = self.factory.get(f'{self.url}?query=file2')
        request.user = self.user
        request.htmx = type('HTMX', (), {'target': None})()
        response = files(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'test_file2', response.content)
        self.assertNotIn(b'test_file1', response.content)

    def test_files_content_type_filtering(self):
        """Test filtering files by content type"""
        self.user.user_permissions.add(
            ContentType.objects.get_for_model(File).permission_set.get(codename='view_file').id
        )
        request = self.factory.get(f'{self.url}?content_type_id={self.content_type.id}')
        request.user = self.user
        request.htmx = type('HTMX', (), {'target': None})()
        response = files(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'test_file2', response.content)

    def test_files_sorting(self):
        """Test sorting files"""
        self.user.user_permissions.add(
            ContentType.objects.get_for_model(File).permission_set.get(codename='view_file').id
        )
        request = self.factory.get(f'{self.url}?sort=-name')
        request.user = self.user
        request.htmx = type('HTMX', (), {'target': None})()
        response = files(request)
        self.assertEqual(response.status_code, 200)
        # Check if files are sorted in reverse order
        content = response.content.decode()
        self.assertTrue(content.index('test_file2') < content.index('test_file1'))




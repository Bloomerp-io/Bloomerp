from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.contrib.contenttypes.models import ContentType

from bloomerp.models import AbstractBloomerpUser, Bookmark
from bloomerp.components.objects.delete_object import delete_object


class DeleteObjectComponentTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.owner = AbstractBloomerpUser.objects.create_user(
            username='owner', password='pass'
        )
        self.other_user = AbstractBloomerpUser.objects.create_user(
            username='other', password='pass'
        )
        self.bookmark = Bookmark.objects.create(
            user=self.owner,
            content_type=ContentType.objects.create(app_label='test_app', model='testmodel'),
            object_id=1,
        )
        self.ct = ContentType.objects.get_for_model(Bookmark)
        self.url = reverse('components_delete_object') + f'?content_type_id={self.ct.id}'

    def test_owner_can_delete_object(self):
        request = self.factory.post(self.url, {'object_id': self.bookmark.id})
        request.user = self.owner
        response = delete_object(request)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Bookmark.objects.filter(id=self.bookmark.id).exists())

    def test_permission_denied_for_other_user(self):
        request = self.factory.post(self.url, {'object_id': self.bookmark.id})
        request.user = self.other_user
        response = delete_object(request)
        self.assertEqual(response.status_code, 403)
        self.assertTrue(Bookmark.objects.filter(id=self.bookmark.id).exists())

    def test_invalid_method(self):
        request = self.factory.get(self.url, {'object_id': self.bookmark.id})
        request.user = self.owner
        response = delete_object(request)
        self.assertEqual(response.status_code, 405)

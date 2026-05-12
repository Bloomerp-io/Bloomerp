from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from bloomerp.tests.base import BaseBloomerpModelTestCase


class TestSaveAvatar(BaseBloomerpModelTestCase):
    def _avatar_url(self, object):
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        return reverse(
            "components_save_avatar",
            kwargs={
                "content_type_id": content_type.pk,
                "object_id": str(object.pk),
            },
        )

    def _image_file(self, name="avatar.gif"):
        return SimpleUploadedFile(
            name,
            (
                b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00"
                b"\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00"
                b"\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )

    def test_save_avatar_updates_object_and_returns_avatar_fragment(self):
        self.client.force_login(self.admin_user)
        customer = self.CustomerModel.objects.first()

        response = self.client.post(
            self._avatar_url(customer),
            data={"avatar": self._image_file()},
        )

        self.assertEqual(response.status_code, 200)
        customer.refresh_from_db()
        self.assertTrue(customer.avatar.name.startswith("avatars/"))
        self.assertContains(response, 'hx-post="', html=False)
        self.assertContains(response, customer.avatar.url, html=False)

    def test_detail_view_avatar_is_clickable_for_user_with_change_access(self):
        self.client.force_login(self.admin_user)
        customer = self.CustomerModel.objects.first()

        response = self.client.get(customer.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'hx-post="{self._avatar_url(customer)}"', html=False)
        self.assertContains(response, 'type="file"', html=False)

    def test_save_avatar_requires_change_access(self):
        self.client.force_login(self.normal_user)
        customer = self.CustomerModel.objects.first()

        response = self.client.post(
            self._avatar_url(customer),
            data={"avatar": self._image_file()},
        )

        self.assertEqual(response.status_code, 403)

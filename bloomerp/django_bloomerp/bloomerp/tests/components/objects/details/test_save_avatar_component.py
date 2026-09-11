from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile

from bloomerp.tests.base import (
    BloomerpComponentTestCase,
    ExpectedResult,
    RequestScenario,
)


class TestSaveAvatarComponent(BloomerpComponentTestCase):
    """Tests saving an object's avatar through the component endpoint."""

    view_name = "components_save_avatar"

    def get_test_scenarios(self) -> list[RequestScenario]:
        customer = self.CustomerModel.objects.first()
        content_type = ContentType.objects.get_for_model(self.CustomerModel)
        view_kwargs = {
            "content_type_id": content_type.pk,
            "object_id": str(customer.pk),
        }
        return [
            RequestScenario(
                name="save avatar",
                method="POST",
                user=self.admin_user,
                view_kwargs=view_kwargs,
                data={"avatar": self._image_file()},
                expected=ExpectedResult(
                    response_validators=[
                        self.contains_text('hx-post="'),
                        self._avatar_was_saved(customer.pk),
                    ],
                ),
            ),
            RequestScenario(
                name="reject user without change access",
                method="POST",
                user=self.normal_user,
                view_kwargs=view_kwargs,
                data={"avatar": self._image_file("forbidden.gif")},
                expected=ExpectedResult(status_code=403),
            ),
        ]

    @staticmethod
    def _image_file(name="avatar.gif"):
        return SimpleUploadedFile(
            name,
            (
                b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00"
                b"\xff\xff\xff,\x00\x00\x00\x00\x01\x00\x01\x00"
                b"\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )

    def _avatar_was_saved(self, object_id):
        def validator(response):
            customer = self.CustomerModel.objects.get(pk=object_id)
            return (
                customer.avatar.name.startswith("avatars/")
                and customer.avatar.url in response.content.decode(
                    response.charset or "utf-8"
                )
            )

        return self._named_validator("avatar_was_saved", validator)

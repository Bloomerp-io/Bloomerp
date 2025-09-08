from django.test import TestCase
from django.urls import reverse, NoReverseMatch
from bloomerp.models import Link, ContentType
from bloomerp.models import Workspace
from bloomerp.models import AbstractBloomerpUser

class LinkModelTests(TestCase):
    def setUp(self):
        pass

    def test_link_is_valid(self):
        # Create a valid link

        valid_link = Link.objects.filter(url="content_types_list").first()
        self.assertTrue(valid_link.is_valid())

        # Create an invalid link
        invalid_link = Link.objects.create(
            name="Invalid Link",
            url="invalid:url",
            level="APP",
            is_absolute_url=False,
            content_type=ContentType.objects.first()
        )
        self.assertFalse(invalid_link.is_valid())

    def test_invalid_workspace_link(self):
        # Create user
        user = AbstractBloomerpUser.objects.create_user(
            username="test_user",
            password="test_password"
        )

        # Create an invalid Link
        invalid_link = Link.objects.create(
            name="Invalid Link",
            url="content_types_list",
            level="APP",
            is_absolute_url=False,
            content_type=ContentType.objects.first()
        )

        # Get valid link
        valid_link = Link.objects.filter(url="content_types_list").first()

        # Create the workspace content
        content = {
            "content" : [
                {
                    "type": "link",
                    "size" : 12,
                    "data" :
                        {"link_id" : invalid_link.id}
                },
                {
                    "type": "link",
                    "size" : 12,
                    "data" :
                        {"link_id" : valid_link.id}
                },
                {
                    "type": "link_list",
                    "size" : 12,
                    "data" :
                        {"links" : [invalid_link.id, valid_link.id]}
                }
            ]
        }
        
        # Create the workspace
        workspace = Workspace.objects.create(
            name="Test Workspace",
            content=content,
            user = user
            )
        
        # Run the 
        workspace.remove_links_from_content(links=[invalid_link])

        # Check that the invalid link was removed
        removed_content = {
            "content" : [
                {
                    "type": "link",
                    "size" : 12,
                    "data" :
                        {"link_id" : valid_link.id}
                },
                {
                    "type": "link_list",
                    "size" : 12,
                    "data" :
                        {"links" : [valid_link.id]}
                }
            ]
        }

        self.assertEqual(workspace.content, removed_content)
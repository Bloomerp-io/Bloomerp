from django.test import TestCase
from bloomerp.router import _auto_generate_url_name
from bloomerp.router import _generate_path
from bloomerp.router import _generate_name
from bloomerp.router import RouteType


class TestRoute(TestCase):
    def test_auto_generate_url_name(self):
        from bloomerp.models.workspaces import Workspace
        name = "John Doe"
        
        # 1. Test app level
        url_1 = _auto_generate_url_name(name, RouteType.APP)
        self.assertEqual(url_1, "john_doe")
        
        # 2. Test list level
        url_2 = _auto_generate_url_name(name, RouteType.LIST, Workspace)
        self.assertEqual(url_2, "workspaces_john_doe")
        
        # 3. Test detail level
        url_3 = _auto_generate_url_name(name, RouteType.DETAIL, Workspace)
        self.assertEqual(url_3, "workspaces_detail_john_doe")
        
        # 4. Check if it raises error
        with self.assertRaises(ValueError):
            _auto_generate_url_name(name, RouteType.DETAIL)
        
    def test_generate_path(self):
        from bloomerp.models.workspaces import Workspace
        from bloomerp.models.document_templates import DocumentTemplate

        # 1. Create app level path
        self.assertEqual(_generate_path("john", RouteType.APP), "/john/")
        self.assertEqual(_generate_path("/john/doe", RouteType.APP), "/john/doe/")
        self.assertEqual(_generate_path("john/<int:some_key>/"), "/john/<int:some_key>/")
        
        # 2. Create list level path
        self.assertEqual(_generate_path("/john/doe/", RouteType.LIST, Workspace), "/workpaces/john/doe/")
        self.assertEqual(_generate_path("/john/doe", RouteType.LIST, DocumentTemplate), "/document-templates/john/doe/")
        
        # 3. Create detail level path
        self.assertEqual(_generate_path("/john/doe/", RouteType.DETAIL, Workspace), "/workpaces/<int_or_uuid:pk>/john/doe/")
    
    def test_generate_name(self):
        from bloomerp.models.workspaces import Workspace
        name1 = "John Doe"
        name2 = "A {model}"
        
        def john_doe_view(request):
            pass
        
        class JohnDoeView:
            pass
        
        # 1. Test with name given
        self.assertEqual(_generate_name(name1), "John Doe")
        self.assertEqual(_generate_name(name1, Workspace), "John Doe")
        self.assertEqual(_generate_name(name1, Workspace, john_doe_view), "John Doe")
        
        # 2. Test with name given with formatting option
        self.assertEqual(_generate_name(name2), "A workspace")
        self.assertEqual(_generate_name(name2, Workspace), "A workspace")
        self.assertEqual(_generate_name(name2, Workspace, john_doe_view), "A workspace")
        
        # 3. Test with no name given
        self.assertEqual(_generate_name(None, Workspace, john_doe_view), "John doe view")
        self.assertEqual(_generate_name(None, Workspace, JohnDoeView), "John doe view")
        
        with self.assertRaises(Exception):
            _generate_name(None, None, None)
            
        with self.assertRaises(Exception):
            _generate_name(None, Workspace, None)
from bloomerp.tests.base import BaseBloomerpModelTestCase
from bloomerp.widgets.one_to_many_field_widget import OneToManyFieldWidget

class TestCreateView(BaseBloomerpModelTestCase):
    create_foreign_models = True
    
    # --------------------------------------
    # TESTS
    # --------------------------------------
    def test_widget_skips_some_fields(self):
        """
        UC: We don't want particular fields to be rendered for the one-to-many widget
        Expected result: some fields are skipped
        """
        
        # 0. Set the skipped fields
        SKIPPED_FIELDS = ["created_by", "updated_by", "datetime_created", "datetime_updated"]
        
        # 1. Create the widget using the related model and parent model
        widget = OneToManyFieldWidget(attrs={
            "related_model" : self.CountryModel,
            "parent_model" : self.PlanetModel,
        })
        
        # 2. Render the widget to get the columns
        widget_html = widget.render(name="test_widget", value=None, attrs={})
        
        # 3. Check that the skipped fields are not present in the widget HTML
        for field_name in SKIPPED_FIELDS:
            self.assertNotIn(field_name, widget_html)
            
    def test_widget_renders_fields_given_as_config(self):
        """
        UC: We want widgets with a specific layout config to render the necessary fields
        Expected result: the fields specified in the config are rendered
        """
        
        # 0. Set the fields to be rendered
        RENDERED_FIELDS = ["first_name", "last_name"]
        
        # 1. Create the widget using the related model and parent model, and specify the fields to render
        widget = OneToManyFieldWidget(attrs={
            "related_model" : self.CustomerModel,
            "parent_model" : self.CountryModel,
            "layout_config" : {
                "inline_fields" : RENDERED_FIELDS
            }
        })
        
        # 2. Render the widget to get the columns
        widget_html = widget.render(name="test_widget", value=None, attrs={})
        
        # 3. Check that the specified fields are present in the widget HTML
        for field_name in RENDERED_FIELDS:
            self.assertIn(field_name, widget_html)
            
        self.assertNotIn("age", widget_html)  # Ensure that a field not specified is not rendered
        
    
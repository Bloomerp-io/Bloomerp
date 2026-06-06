from django import forms
from django.test import SimpleTestCase
from django.utils.html import escape

from bloomerp.widgets.code_editor_widget import CodeEditorWidget


class TestCodeEditorWidget(SimpleTestCase):
    def test_json_widget_serializes_python_dict_to_json(self):
        widget = CodeEditorWidget(language='json')

        context = widget.get_context('rule', {'field': 'id', 'value': '52'}, {'id': 'id_rule'})

        self.assertEqual(
            context['widget']['value'],
            '{\n  "field": "id",\n  "value": "52"\n}'
        )

    def test_json_widget_preserves_existing_json_string(self):
        widget = CodeEditorWidget(language='json')

        context = widget.get_context('rule', '{"field":"id","value":"52"}', {'id': 'id_rule'})

        self.assertEqual(
            context['widget']['value'],
            '{\n  "field": "id",\n  "value": "52"\n}'
        )

    def test_non_json_widget_keeps_plain_string_value(self):
        widget = CodeEditorWidget(language='python')

        context = widget.get_context('script', 'print("hello")', {'id': 'id_script'})

        self.assertEqual(context['widget']['value'], 'print("hello")')

    def test_launch_button_renders_cotton_modal(self):
        widget = CodeEditorWidget(language='html', launch_from_button=True)

        html = widget.render('body', '<p>Hello</p>', attrs={'id': 'id_body'})

        self.assertIn('bloomerp-component="modal"', html)
        self.assertNotIn('<c-ui.modal', html)
        self.assertRegex(
            html,
            r'data-modal-id="modal_id_body_[0-9a-f-]+"',
        )
        self.assertRegex(
            html,
            r'bloomerp-open-modal="modal_id_body_[0-9a-f-]+"',
        )
        modal_id = html.split('data-modal-id="', 1)[1].split('"', 1)[0]
        self.assertIn(f'bloomerp-open-modal="{modal_id}"', html)
        self.assertIn(f'id="{modal_id}"', html)
        self.assertIn('name="body"', html)
        self.assertIn(f'>{escape("<p>Hello</p>")}</textarea>', html)

    def test_default_django_widget_template_renders(self):
        field = forms.CharField()

        html = field.widget.render('title', 'Example', attrs={'id': 'id_title'})

        self.assertIn('type="text"', html)
        self.assertIn('value="Example"', html)

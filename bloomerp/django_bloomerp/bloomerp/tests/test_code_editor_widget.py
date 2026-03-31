from django.test import SimpleTestCase

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
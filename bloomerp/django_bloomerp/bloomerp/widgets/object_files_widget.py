from django import forms


class ObjectFilesWidget(forms.Widget):
    template_name = "widgets/object_files_widget.html"

    def format_value(self, value):
        if value is None:
            return []
        if hasattr(value, "all"):
            return list(value.all().order_by("-datetime_created"))
        if isinstance(value, (list, tuple)):
            return value
        return []

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["files"] = self.format_value(value)
        context["multiple"] = True
        return context

    def value_from_datadict(self, data, files, name):
        return files.getlist(name)

from bloomerp.forms.core import BloomerpModelForm
from bloomerp.forms.model_form import bloomerp_modelform_factory


from django.http import HttpResponse
from django.shortcuts import redirect
from django.views.generic.edit import ModelFormMixin


class BloomerpModelFormViewMixin(ModelFormMixin):
    '''
    A mixin that provides a form view for a model.

    It includes the following features:

        - It uses the BloomerpModelForm form class
        - It sets the user and model attributes on the form
        - It saves the form instance to the database
        - It sets the updated_by attribute on the instance if it exists
        - It sets the created_by attribute on the instance if it exists
    '''
    exclude = []
    form_class = BloomerpModelForm

    # TODO: this needs to be changed becauauas

    def get_form_kwargs(self) -> dict:
        kwargs = super().get_form_kwargs()
        return kwargs

    def form_valid(self, form: BloomerpModelForm) -> HttpResponse:
        # Call form valid on super class to make sure messages are displayed
        super().form_valid(form)

        # Save the form instance but don't commit to the database yet
        obj = form.save(commit=False)

        # Check if the instance has 'last_updated_by' attribute and set it
        if hasattr(obj, "updated_by"):
            obj.updated_by = self.request.user

        # Check if the instance has 'created_by' attribute and set it
        if hasattr(obj, "created_by") and not obj.created_by:
            obj.created_by = self.request.user

        # Now save the object to the database
        obj.save()

        # Check if the form has a save_m2m method and call it
        if hasattr(form, "save_m2m"):
            form.save_m2m()

        # Check if the form has an update_file_fields method and call it
        if hasattr(obj, "save_file_fields"):
            obj.save_file_fields()

        return redirect(self.get_success_url())

    def get_form(self, form_class=None) -> BloomerpModelForm:
        form = super().get_form(form_class)

        if "updated_by" in form.fields:
            del form.fields["updated_by"]

        if "created_by" in form.fields:
            del form.fields["created_by"]

        return form

    def get_form_class(self) -> BloomerpModelForm:
        return self.get_form_class_for_fields("__all__")

    def get_form_class_for_fields(self, fields: list[str] | str) -> BloomerpModelForm:
        return bloomerp_modelform_factory(
            model_cls=self.model,
            fields=fields,
        )
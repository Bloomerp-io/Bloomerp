from django.forms.models import modelform_factory
from django.shortcuts import render
from bloomerp.utils.filters import dynamic_filterset_factory
from bloomerp.models import Workspace


def test_workspace(request):
    workspace = Workspace.objects.first()


    return render(request, 'test_view.html', {'workspace': workspace})


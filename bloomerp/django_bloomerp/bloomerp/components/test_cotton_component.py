from django.shortcuts import render
from bloomerp.router import router
from bloomerp.automation.defintion import WorkflowNodeType

@router.register(
    path='components/test_cotton_component/', 
    name='components_test_cotton_component'
    )
def test_cotton_component(request):
    '''
    A test view for cotton component development.
    '''
    
    return render(
        request,
        'components/test_cotton_component.html',
        context={
            "node_types" : WorkflowNodeType.members(),
        }
    )
from bloomerp.router import router
from bloomerp.views.detail.base_detail import BaseBloomerpDetailView

from ..models.sample import SampleModel

@router.register("/function-based-view/")
def sample_function_based_view(request):
    return {"message": "Hello from the function-based view!"}


@router.register(
    path="/class-based-view/",
    route_type="detail",
    models=[SampleModel]
    )
class SampleClassBasedView(BaseBloomerpDetailView):
    template_name = "sample_detail_view.html"
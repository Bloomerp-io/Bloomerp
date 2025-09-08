from rest_framework import viewsets
from django_filters import rest_framework as filters
from rest_framework.permissions import IsAuthenticated, BasePermission

class ViewPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm(f'{view.model._meta.app_label}.view_{view.model._meta.model_name}')

class AddPermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm(f'{view.model._meta.app_label}.add_{view.model._meta.model_name}')

class ChangePermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm(f'{view.model._meta.app_label}.change_{view.model._meta.model_name}')

class DeletePermission(BasePermission):
    def has_permission(self, request, view):
        return request.user.has_perm(f'{view.model._meta.app_label}.delete_{view.model._meta.model_name}')

class BloomerpModelViewSet(viewsets.ModelViewSet):
    # The model will be injected dynamically when the viewset is initialized
    queryset = None
    serializer_class = None
    filter_backends = (filters.DjangoFilterBackend,)
    filterset_fields = '__all__'
    permission_classes = (IsAuthenticated,)

    def get_permissions(self):
        if self.action == 'list' or self.action == 'retrieve':
            self.permission_classes = [IsAuthenticated, ViewPermission]
        elif self.action == 'create':
            self.permission_classes = [IsAuthenticated, AddPermission]
        elif self.action in ['update', 'partial_update']:
            self.permission_classes = [IsAuthenticated, ChangePermission]
        elif self.action == 'destroy':
            self.permission_classes = [IsAuthenticated, DeletePermission]
        return super().get_permissions()

    def get_queryset(self):
        return self.model.objects.all()

    def get_serializer_class(self):
        return self.serializer_class

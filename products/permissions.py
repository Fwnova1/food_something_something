from rest_framework.permissions import BasePermission

class IsProducer(BasePermission):
    def has_permission(self, request, view):
        return request.user.role == "producer"
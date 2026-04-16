from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Home
    path("", TemplateView.as_view(
        template_name="home.html"
    ), name="home"
    ),

    # Frontend
    path("", include("products.urls")),

    # API
    path("api/", include("products.api_urls")),

    # Django admin (kept after frontend so /admin/ai-* routes resolve first)
    path('admin/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

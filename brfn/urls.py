from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),

    # Home
    path("", TemplateView.as_view(
        template_name="pages/home.html"
    ), name="home"
    ),

    # Frontend
    path("", include("products.urls")),

    # API
    path("api/", include("products.api_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


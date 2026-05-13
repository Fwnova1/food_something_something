from django.contrib import admin

from brfn.admin_actions import AdminActionSelectLabelMixin

from .models import Category, ContentPost, Producer, Product, ProductReview, QualityInspection


class _ProductAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    pass


class _CategoryAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    pass


class _ProducerAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    pass


class _ContentPostAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    pass


class _QualityInspectionAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    pass


@admin.register(ProductReview)
class ProductReviewAdmin(AdminActionSelectLabelMixin, admin.ModelAdmin):
    list_display = ("id", "product", "user", "rating", "status", "created_at")
    list_filter = ("status", "rating", "created_at")
    search_fields = ("product__name", "user__username", "user__email", "title", "comment")
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("product", "user")


admin.site.register(Product, _ProductAdmin)
admin.site.register(Category, _CategoryAdmin)
admin.site.register(Producer, _ProducerAdmin)
admin.site.register(ContentPost, _ContentPostAdmin)
admin.site.register(QualityInspection, _QualityInspectionAdmin)

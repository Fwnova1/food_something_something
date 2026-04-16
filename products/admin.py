from django.contrib import admin

from .models import Category, ContentPost, Producer, Product, ProductReview, QualityInspection

admin.site.register(Product)
admin.site.register(Category)
admin.site.register(Producer)
admin.site.register(ProductReview)
admin.site.register(ContentPost)
admin.site.register(QualityInspection)

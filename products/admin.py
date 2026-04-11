from django.contrib import admin
from .models import Product, Category, Producer, ProductReview, ContentPost

admin.site.register(Product)
admin.site.register(Category)
admin.site.register(Producer)
admin.site.register(ProductReview)
admin.site.register(ContentPost)

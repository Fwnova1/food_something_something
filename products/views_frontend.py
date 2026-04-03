from django.shortcuts import render
from .models import Product, Category


def product_list(request):

    products = Product.objects.all()
    categories = Category.objects.all()

    category_id = request.GET.get("category")

    if category_id:
        products = products.filter(category_id=category_id)

    context = {
        "products": products,
        "categories": categories
    }

    return render(request, "product_list.html", context)


def product_detail(request, pk):

    product = Product.objects.get(id=pk)

    return render(
        request,
        "product_detail.html",
        {"product": product}
    )
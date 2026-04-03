from django.db import models
from users.models import User

class Category(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Producer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    farm_name = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    postcode = models.CharField(max_length=20)

    def __str__(self):
        return self.farm_name


class Product(models.Model):
    name = models.CharField(max_length=200)
    description = models.TextField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    category = models.ForeignKey(Category, on_delete=models.CASCADE)

    producer = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE
    )

    image = models.ImageField(upload_to="products/", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
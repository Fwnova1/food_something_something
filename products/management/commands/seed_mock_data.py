import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from orders.models import Cart, CartItem, Order, OrderItem
from products.models import Category, ContentPost, Product


User = get_user_model()


class Command(BaseCommand):
    help = "Seed the database with mock data for local development/demo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Remove previously generated mock data before seeding again.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Random seed for deterministic mock data generation.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(options["seed"])

        if options["reset"]:
            self._reset_mock_data()

        admin_user = self._create_admin()
        producers = self._create_producers()
        customers = self._create_customers()
        categories = self._create_categories()
        products = self._create_products(producers, categories)
        self._create_content_posts(producers, categories, products)
        self._create_carts(customers, products)
        self._create_orders(customers, products)

        self.stdout.write(self.style.SUCCESS("Mock data seeded successfully."))
        self.stdout.write("")
        self.stdout.write(self.style.NOTICE("Sample credentials:"))
        self.stdout.write("  Admin:    admin / admin123")
        self.stdout.write("  Producer: producer1 / password123")
        self.stdout.write("  Customer: customer1 / password123")
        self.stdout.write("")
        self.stdout.write(f"Admin user: {admin_user.username}")
        self.stdout.write(f"Created {len(producers)} producers, {len(customers)} customers.")
        self.stdout.write(f"Created {len(categories)} categories, {len(products)} products.")

    def _reset_mock_data(self):
        mock_domain = "@mock.local"

        # Remove transactional data first.
        OrderItem.objects.all().delete()
        Order.objects.all().delete()
        CartItem.objects.all().delete()
        Cart.objects.all().delete()

        # Remove catalog data.
        ContentPost.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()

        # Remove only mock users (keep any real/admin users).
        User.objects.filter(email__iendswith=mock_domain).delete()

        self.stdout.write(self.style.WARNING("Previous mock data removed."))

    def _create_admin(self):
        admin, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@mock.local",
                "role": "admin",
                "is_staff": True,
                "is_superuser": True,
                "first_name": "System",
                "last_name": "Admin",
                "terms_accepted": True,
            },
        )
        admin.set_password("admin123")
        admin.is_staff = True
        admin.is_superuser = True
        admin.role = "admin"
        admin.save()
        if created:
            self.stdout.write("Created admin user.")
        return admin

    def _create_producers(self):
        producer_specs = [
            ("producer1", "Bristol Valley Farm", "Jane Smith", "BS1 4DJ"),
            ("producer2", "Hillside Dairy", "Mark Hill", "BS3 2AA"),
            ("producer3", "Avon Bakery Co.", "Lucy Brown", "BS5 8RT"),
            ("producer4", "Green Meadow Organics", "Tom Wright", "BS7 1PL"),
        ]

        producers = []
        for username, business_name, contact_name, postcode in producer_specs:
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@mock.local",
                    "role": "producer",
                    "business_name": business_name,
                    "contact_name": contact_name,
                    "phone": "01179 123456",
                    "address": f"Farm Road, Bristol ({business_name})",
                    "postcode": postcode,
                    "terms_accepted": True,
                },
            )
            user.role = "producer"
            user.business_name = business_name
            user.contact_name = contact_name
            user.phone = user.phone or "01179 123456"
            user.postcode = user.postcode or postcode
            user.terms_accepted = True
            user.set_password("password123")
            user.save()
            producers.append(user)
        return producers

    def _create_customers(self):
        customer_specs = [
            ("customer1", "Robert Johnson", "BS1 5JG"),
            ("customer2", "Emily Carter", "BS6 6AA"),
            ("customer3", "Daniel Lewis", "BS8 1HB"),
            ("customer4", "Sophie Turner", "BS9 3LD"),
            ("customer5", "Michael Scott", "BS4 7PY"),
        ]

        customers = []
        for username, full_name, postcode in customer_specs:
            first_name, last_name = full_name.split(" ", 1)
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={
                    "email": f"{username}@mock.local",
                    "role": "customer",
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": "07700 900123",
                    "address": f"{random.randint(10, 99)} Park Street, Bristol",
                    "postcode": postcode,
                    "terms_accepted": True,
                },
            )
            user.role = "customer"
            user.first_name = first_name
            user.last_name = last_name
            user.terms_accepted = True
            user.set_password("password123")
            user.save()
            customers.append(user)
        return customers

    def _create_categories(self):
        category_specs = [
            ("Vegetables", "Seasonal local vegetables."),
            ("Dairy & Eggs", "Fresh local milk, cheese, and eggs."),
            ("Bakery", "Bread, pastries, and baked goods."),
            ("Preserves", "Jams, sauces, and preserved products."),
            ("Fruit", "Fresh fruit from local farms."),
        ]

        categories = []
        for name, description in category_specs:
            category, _ = Category.objects.get_or_create(
                name=name,
                defaults={"description": description},
            )
            categories.append(category)
        return categories

    def _create_products(self, producers, categories):
        product_specs = [
            ("Organic Carrots", "Crunchy organic carrots from open fields.", "kg", "in_season", "No common allergens", True),
            ("Free Range Eggs", "Fresh eggs collected daily.", "dozen", "year_round", "Contains eggs", False),
            ("Sourdough Loaf", "Slow-fermented artisan sourdough bread.", "loaf", "year_round", "Contains gluten", False),
            ("Strawberry Jam", "Handmade jam using local strawberries.", "jar", "year_round", "No common allergens", False),
            ("Organic Milk", "Creamy organic milk from grass-fed cows.", "litre", "year_round", "Contains milk", True),
            ("Spinach", "Tender green spinach leaves.", "bundle", "in_season", "No common allergens", True),
            ("Walnut Bread", "Crusty bread with toasted walnuts.", "loaf", "year_round", "Contains gluten, nuts", False),
            ("Apples", "Fresh seasonal apples.", "kg", "in_season", "No common allergens", False),
            ("Cheddar Cheese", "Mature farmhouse cheddar.", "block", "year_round", "Contains milk", False),
            ("Tomato Sauce", "Rich passata made from ripe tomatoes.", "bottle", "year_round", "No common allergens", False),
        ]

        products = []
        today = timezone.localdate()
        for idx, spec in enumerate(product_specs):
            name, description, unit, availability, allergen_info, is_organic = spec
            category = categories[idx % len(categories)]
            producer = producers[idx % len(producers)]
            price = Decimal(random.randint(150, 1200)) / Decimal("100")
            stock_quantity = random.randint(12, 120)

            seasonal_start = None
            seasonal_end = None
            if availability == "in_season":
                seasonal_start = today.replace(month=3, day=1)
                seasonal_end = today.replace(month=10, day=31)

            product = Product.objects.create(
                name=name,
                description=description,
                price=price,
                unit=unit,
                category=category,
                producer=producer,
                availability=availability,
                stock_quantity=stock_quantity,
                low_stock_threshold=10,
                allergen_info=allergen_info,
                is_organic=is_organic,
                harvest_date=today,
                seasonal_start=seasonal_start,
                seasonal_end=seasonal_end,
            )
            products.append(product)
        return products

    def _create_carts(self, customers, products):
        for customer in customers[:3]:
            cart, _ = Cart.objects.get_or_create(user=customer)
            chosen = random.sample(products, k=3)
            for product in chosen:
                quantity = random.randint(1, 3)
                CartItem.objects.update_or_create(
                    cart=cart,
                    product=product,
                    defaults={"quantity": min(quantity, product.stock_quantity)},
                )

    def _create_orders(self, customers, products):
        status_pool = ["pending", "confirmed", "shipped", "delivered"]
        for customer in customers:
            for _ in range(2):
                chosen_products = random.sample(products, k=random.randint(2, 5))
                status = random.choice(status_pool)
                order = Order.objects.create(
                    user=customer,
                    total=Decimal("0.00"),
                    status=status,
                    delivery_address=customer.address,
                    delivery_postcode=customer.postcode,
                    customer_note="Leave at front desk if unavailable.",
                )

                total = Decimal("0.00")
                for product in chosen_products:
                    quantity = random.randint(1, 3)
                    line_total = product.price * quantity
                    total += line_total

                    if status in ("shipped", "delivered"):
                        producer_shipped = True
                        producer_shipped_at = timezone.now() - timedelta(days=random.randint(1, 5))
                    else:
                        producer_shipped = False
                        producer_shipped_at = None

                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price=product.price,
                        producer_shipped=producer_shipped,
                        producer_shipped_at=producer_shipped_at,
                    )

                order.total = total.quantize(Decimal("0.01"))
                order.save(update_fields=["total"])

    def _create_content_posts(self, producers, categories, products):
        now = timezone.now()
        category_map = {c.name: c for c in categories}
        product_map = {p.name: p for p in products}

        recipes = [
            {
                "title": "Roasted Root Vegetable Medley",
                "summary": "A simple weeknight tray-bake using local carrots and seasonal roots.",
                "body": "This recipe highlights naturally sweet local vegetables and minimal prep.",
                "ingredients": "1kg Organic Carrots\n500g potatoes\n2 tbsp olive oil\n1 tsp sea salt\n1 tsp thyme",
                "steps": "Preheat oven to 200C.\nCut vegetables evenly.\nToss with oil, salt, thyme.\nRoast 35-40 minutes, turning once.",
                "category": "Vegetables",
                "related_product": "Organic Carrots",
                "author": producers[0],
            },
            {
                "title": "Farmhouse Cheddar Toastie",
                "summary": "Crisp sourdough with melted mature cheddar for a quick local lunch.",
                "body": "A classic toastie using artisan bread and local dairy.",
                "ingredients": "2 slices Sourdough Loaf\n80g Cheddar Cheese\n1 tsp butter",
                "steps": "Butter bread.\nAdd grated cheese.\nToast in pan or press until golden and melted.",
                "category": "Dairy & Eggs",
                "related_product": "Cheddar Cheese",
                "author": producers[1],
            },
            {
                "title": "Apple Jam Breakfast Bowl",
                "summary": "A light breakfast bowl topped with fresh apples and strawberry jam.",
                "body": "Balanced sweetness from seasonal fruit and small-batch preserve.",
                "ingredients": "1 apple\n1 tbsp Strawberry Jam\nyogurt or oats base",
                "steps": "Slice apple thinly.\nAdd to bowl with yogurt/oats.\nTop with strawberry jam.",
                "category": "Fruit",
                "related_product": "Apples",
                "author": producers[2],
            },
        ]

        stories = [
            {
                "title": "Early Spring Harvest at Bristol Valley Farm",
                "summary": "How we plan carrot rotations and soil health before the first major harvest.",
                "body": "This season we focused on soil moisture retention, companion planting, and lower tillage passes to improve carrot quality.",
                "category": "Vegetables",
                "related_product": "Organic Carrots",
                "author": producers[0],
            },
            {
                "title": "Inside the Dairy: Morning Milking Routine",
                "summary": "A look at hygiene checks and cooling workflow that keep milk quality consistent.",
                "body": "From first milking to rapid cooling, our process is built for food safety and consistent flavor week after week.",
                "category": "Dairy & Eggs",
                "related_product": "Organic Milk",
                "author": producers[1],
            },
            {
                "title": "Why Our Bakery Ferments Overnight",
                "summary": "Slow fermentation improves texture, digestibility, and flavor depth.",
                "body": "Overnight fermentation gives our sourdough better structure and a balanced tang while reducing waste through tighter planning.",
                "category": "Bakery",
                "related_product": "Sourdough Loaf",
                "author": producers[2],
            },
        ]

        def create_post(item, content_type):
            title = item["title"]
            slug_base = slugify(title)[:180] or "post"
            slug = slug_base
            suffix = 2
            while ContentPost.objects.filter(slug=slug).exists():
                slug = f"{slug_base}-{suffix}"
                suffix += 1

            ContentPost.objects.create(
                title=title,
                slug=slug,
                content_type=content_type,
                status="published",
                summary=item["summary"],
                body=item["body"],
                ingredients=item.get("ingredients", ""),
                steps=item.get("steps", ""),
                category=category_map.get(item["category"]),
                related_product=product_map.get(item["related_product"]),
                author=item["author"],
                published_at=now - timedelta(days=random.randint(1, 21)),
            )

        for recipe in recipes:
            create_post(recipe, "recipe")
        for story in stories:
            create_post(story, "story")

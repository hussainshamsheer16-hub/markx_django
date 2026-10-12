from django.conf import settings
from django.db.models import Q

from .cart import Cart
from .models import Category, Wishlist


def site(request):
    wishlist_ids = list(Wishlist.objects.filter(user=request.user).values_list("product_id", flat=True)) if request.user.is_authenticated else []
    categories = Category.objects.filter(
        Q(name__in=("Shirts", "Trousers", "Pairs"))
        | Q(products__active=True, products__collection="men")
    ).distinct()
    category_order = {"Shirts": 0, "Trousers": 1, "Pairs": 2}
    shop_categories = sorted(categories, key=lambda category: (category_order.get(category.name, 3), category.order, category.name))
    return {
        "MX": settings.MARKX,
        "cart_count": len(Cart(request)),
        "nav_active": request.resolver_match.url_name if request.resolver_match else "",
        "shop_categories": shop_categories,
        "wishlist_ids": wishlist_ids,
    }

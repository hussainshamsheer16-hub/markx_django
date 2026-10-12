import json
import secrets
import csv
from decimal import Decimal
from datetime import timedelta
from io import TextIOWrapper, BytesIO

from django import forms
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.forms import SetPasswordForm
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.forms import modelform_factory
from django.db.models.deletion import ProtectedError
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
from django.http import HttpResponse, JsonResponse
from django.http import HttpResponseForbidden
from functools import wraps
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.cache import never_cache

from .cart import Cart
from .email_notifications import send_newsletter_welcome_email
from .forms import (AccountCreationForm, AccountProfileForm, BulkForm,
                    CheckoutForm, CommentForm, ContactForm, CustomForm, EmailAuthenticationForm, ReviewForm, TrackOrderForm)
from .models import (BulkRequest, Category, Comment, ContactMessage, Coupon, CustomRequest,
                     NewsletterSubscriber, Order, OrderItem, Product, ProductVariant, Review, Wishlist,
                     recommend_size_for, OTPChallenge, BackInStockSubscription,
                     ReferralCode, LoyaltyTransaction)
from .models import AbandonedCart
from .models import Expense, OrderAuditLog
from .otp import send_cod_otp, verify_cod_otp
from .forms import normalize_pakistani_mobile

STAFF_MANAGEMENT_MODELS = {
    "products": {
        "title": "Products",
        "model": Product,
        "show_thumbnail": True,
        "columns": (("name", "Product"), ("category", "Category"), ("price", "Price"), ("cost_price", "Cost"), ("stock_qty", "Stock qty"), ("in_stock", "In stock"), ("active", "Visible")),
        "search_fields": ("name", "slug", "description", "category__name"),
        "filters": {
            "active": (("true", "Visible"), ("false", "Hidden")),
            "in_stock": (("true", "In stock"), ("false", "Out of stock")),
        },
        "form_fields": ("name", "slug", "category", "collection", "product_type", "badge", "description", "size_guide", "price", "cost_price", "old_price", "rating", "reviews", "colors", "sizes", "image", "image2", "image3", "customizable", "featured", "stock_qty", "in_stock", "active"),
        "excluded_fields": ("manual_rating", "manual_reviews"),
        "select_related": ("category",),
        "ordering": ("-featured", "name"),
    },
    "categories": {
        "title": "Categories",
        "model": Category,
        "show_thumbnail": True,
        "columns": (("name", "Category"), ("slug", "Slug"), ("tagline", "Tagline"), ("show_on_home", "On homepage"), ("order", "Order")),
        "search_fields": ("name", "slug", "tagline"),
        "filters": {"show_on_home": (("true", "On homepage"), ("false", "Hidden"))},
        "form_fields": ("name", "slug", "tagline", "image", "show_on_home", "order"),
        "ordering": ("order", "name"),
    },
    "orders": {
        "title": "Orders",
        "model": Order,
        "columns": (("number", "Order"), ("full_name", "Customer"), ("phone", "Phone"), ("total", "Total"), ("status", "Status"), ("created", "Placed"), ("payment_confirmed_by", "Confirmed by")),
        "search_fields": ("number", "full_name", "phone", "email"),
        "filters": {"status": Order.STATUS, "payment_method": Order.PAYMENT},
        "form_fields": ("status", "notes", "payment_confirmed", "payment_confirmed_by", "shipping_cost"),
        "readonly_fields": ("number", "full_name", "email", "phone", "address", "city", "payment_method", "coupon_code", "subtotal", "discount", "delivery", "total", "created", "payment_confirmed_by"),
        "ordering": ("-created",),
    },
    "custom-requests": {
        "title": "Custom requests",
        "model": CustomRequest,
        "show_thumbnail": True,
        "thumbnail_field": "design_file",
        "columns": (("id", "Request"), ("name", "Customer"), ("phone", "Phone"), ("tshirt_type", "Item"), ("quantity", "Quantity"), ("status", "Status"), ("created", "Received")),
        "search_fields": ("name", "phone", "email", "custom_text"),
        "filters": {"status": CustomRequest.STATUS},
        "form_fields": ("status",),
        "readonly_fields": ("name", "phone", "email", "tshirt_type", "color", "size", "quantity", "placement", "custom_text", "custom_text_color", "design_file", "notes", "created"),
        "ordering": ("-created",),
    },
    "bulk-requests": {
        "title": "Bulk requests",
        "model": BulkRequest,
        "columns": (("id", "Request"), ("organization", "Organization"), ("contact_person", "Contact"), ("order_type", "Order type"), ("quantity_range", "Quantity"), ("status", "Status"), ("created", "Received")),
        "search_fields": ("organization", "contact_person", "email", "phone"),
        "filters": {"status": BulkRequest.STATUS},
        "form_fields": ("status",),
        "readonly_fields": ("organization", "contact_person", "phone", "email", "order_type", "tshirt_type", "printing_type", "quantity_range", "notes", "created"),
        "ordering": ("-created",),
    },
    "subscribers": {
        "title": "Newsletter subscribers",
        "model": NewsletterSubscriber,
        "columns": (("email", "Email"), ("created", "Subscribed")),
        "search_fields": ("email",),
        "filters": {},
        "form_fields": (),
        "can_add": False,
        "can_edit": False,
        "can_delete": True,
        "ordering": ("-created",),
    },
    "messages": {
        "title": "Contact messages",
        "model": ContactMessage,
        "columns": (("name", "Name"), ("subject", "Subject"), ("email", "Email"), ("handled", "Handled"), ("created", "Received")),
        "search_fields": ("name", "email", "subject", "message"),
        "filters": {"handled": (("true", "Handled"), ("false", "Needs reply"))},
        "form_fields": ("handled",),
        "readonly_fields": ("name", "email", "phone", "subject", "message", "created"),
        "ordering": ("-created",),
    },
    "feedback": {
        "title": "Customer feedback",
        "model": Comment,
        "columns": (("name", "Customer"), ("message", "Feedback"), ("created", "Received")),
        "search_fields": ("name", "message", "user__username"),
        "filters": {},
        "form_fields": (),
        "can_add": False,
        "can_edit": False,
        "can_delete": True,
        "staff_can_delete": True,
        "ordering": ("-created",),
    },
}

STORE_CATEGORY_NAMES = ("Shirts", "Trousers", "Pairs")


def _store_categories():
    category_filter = Q(name__in=STORE_CATEGORY_NAMES)
    category_order = Case(
        *[When(name=name, then=position) for position, name in enumerate(STORE_CATEGORY_NAMES)],
        default=len(STORE_CATEGORY_NAMES),
        output_field=IntegerField(),
    )
    available_products = Product.objects.storefront().available()
    return Category.objects.filter(
        category_filter, products__in=available_products,
    ).distinct().order_by(category_order, "order", "name")


class StockUnavailable(Exception):
    pass


class CouponUnavailable(Exception):
    pass


store_admin_required = user_passes_test(
    lambda user: user.is_active and (user.is_superuser or (user.is_staff and user.groups.filter(name="Manager").exists())),
    login_url="/admin/login/",
)

def owner_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('store:account')}?next={request.path}")
        if not request.user.is_active or not request.user.is_superuser:
            return HttpResponseForbidden()
        return view(request, *args, **kwargs)
    return wrapped


def _staff_management_spec(model_key):
    spec = STAFF_MANAGEMENT_MODELS.get(model_key)
    if spec is None:
        from django.http import Http404
        raise Http404("Management section not found")
    return spec


def _staff_display_value(obj, field_name):
    if isinstance(obj, Comment) and field_name == "message":
        return obj.message[:120] + ("…" if len(obj.message) > 120 else "")
    display_method = getattr(obj, f"get_{field_name}_display", None)
    value = display_method() if display_method else getattr(obj, field_name)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if field_name in {"price", "old_price", "total", "subtotal", "discount", "delivery"} and value is not None:
        return f"Rs. {value:,}"
    if field_name == "payment_confirmed_by" and value:
        return value.get_full_name() or value.get_username()
    if hasattr(value, "strftime"):
        return value.strftime("%d %b %Y, %H:%M")
    return value if value not in (None, "") else "—"


def home(request):
    base = Product.objects.storefront().available().select_related("category")
    featured = base.order_by("-featured", "-created", "id")
    home_comments = Comment.objects.filter(published=True).order_by("-created")[:12]

    def _row(slug, limit=4):
        category_products = base.filter(category__slug=slug)
        if slug == "pairs":
            category_products = base.filter(Q(category__slug=slug) | Q(category__name__iexact="Pairs"))
        return list(category_products.order_by("-featured", "-created", "id")[:limit])

    shirts, trousers, pairs = _row("shirts"), _row("trousers"), _row("pairs")
    tiles = []
    for slug, label_en, label_ur, items in (
        ("shirts", "Shirts", "شرٹس", shirts),
        ("trousers", "Trousers", "ٹراؤزر", trousers),
        ("pairs", "Pairs", "جوڑے", pairs),
    ):
        cover = None
        for item in items:
            if item.image:
                cover = item
                break
        category = Category.objects.filter(slug=slug).first()
        cover_url = category.image.url if category and category.image else (cover.image.url if cover else "")
        tile_products = base.filter(category__slug=slug)
        if slug == "pairs":
            tile_products = base.filter(Q(category__slug=slug) | Q(category__name__iexact="Pairs"))
        tiles.append({"slug": slug, "en": label_en, "ur": label_ur, "cover_url": cover_url, "count": tile_products.count()})
    return render(request, "store/home.html", {
        "featured": featured, "shirts": shirts, "trousers": trousers, "pairs": pairs, "category_tiles": tiles,
        "home_comments": home_comments,
    })


def robots_txt(request):
    sitemap_url = request.build_absolute_uri(reverse("sitemap"))
    return HttpResponse(
        f"User-agent: *\nAllow: /\nDisallow: /admin/\nSitemap: {sitemap_url}\n",
        content_type="text/plain",
    )


@require_POST
def set_language(request):
    """Persist the storefront language choice in the visitor's session."""
    language = request.POST.get("language", "en")
    if language in {"en", "ur"}:
        request.session["site_language"] = language
    next_url = request.POST.get("next", "") or request.META.get("HTTP_REFERER", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("store:home")


@login_required(login_url="store:account")
@require_POST
def checkout_otp(request):
    action = request.POST.get("action")
    try:
        phone = normalize_pakistani_mobile(request.POST.get("phone", ""))
    except Exception:
        messages.error(request, "Enter a valid Pakistani phone number first.")
        return redirect("store:checkout")
    if action == "send":
        ok, text = send_cod_otp(phone)
        (messages.success if ok else messages.error)(request, text)
    elif action == "verify":
        if verify_cod_otp(phone, request.POST.get("otp_code", "")):
            request.session["verified_cod_phone"] = phone
            messages.success(request, "Phone number verified.")
        else:
            messages.error(request, "The code is invalid, expired, or has reached its attempt limit.")
    return redirect("store:checkout")


@require_POST
def stock_alert_subscribe(request, pk):
    product = get_object_or_404(Product.objects.storefront(), pk=pk)
    size, color = request.POST.get("size", "").strip(), request.POST.get("color", "").strip()
    variant = ProductVariant.objects.filter(product=product, size__iexact=size, color__iexact=color, active=True).first()
    email = request.POST.get("email", "").strip()
    phone = request.POST.get("phone", "").strip()
    if request.user.is_authenticated and not email:
        email = request.user.email
    try:
        if email:
            validate_email(email)
        if phone:
            phone = normalize_pakistani_mobile(phone)
    except ValidationError:
        messages.error(request, "Enter a valid email address or Pakistani mobile number.")
        return redirect(product.get_absolute_url())
    if not variant or variant.stock_qty > 0 or (not email and not phone):
        messages.error(request, "Choose an unavailable size and colour and provide an email or phone number.")
    else:
        BackInStockSubscription.objects.get_or_create(variant=variant, email=email, phone=phone, defaults={"product": product})
        messages.success(request, "We will notify you when this size and colour is available.")
    return redirect(product.get_absolute_url())


def shop(request):
    qs = Product.objects.storefront().available().select_related("category")
    cat = request.GET.get("category", "")
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "")
    max_price = request.GET.get("max", "")
    size_filter = request.GET.get("size", "").strip()
    color_filter = request.GET.get("color", "").strip()
    if cat.casefold() in {"tracksuits", "pairs"}:
        qs = qs.filter(category__name__iexact="Pairs")
    elif cat:
        qs = qs.filter(Q(category__slug=cat) | Q(category__name__iexact=cat))
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(category__name__icontains=q))
    if max_price.isdigit():
        qs = qs.filter(price__lte=int(max_price))
    if size_filter:
        qs = qs.filter(_comma_token_filter("sizes", size_filter))
    if color_filter:
        qs = qs.filter(_comma_token_filter("colors", color_filter))
    qs = qs.order_by({"low": "price", "high": "-price", "rating": "-rating"}.get(sort, "-featured"), "id")
    paginator = Paginator(qs, 12)
    page_obj = paginator.get_page(request.GET.get("page"))
    catalog_values = Product.objects.storefront().available().values_list("sizes", "colors")
    sizes, colors = set(), set()
    for product_sizes, product_colors in catalog_values:
        sizes.update(token.strip() for token in product_sizes.split(",") if token.strip())
        colors.update(token.strip() for token in product_colors.split(",") if token.strip())
    query_string = request.GET.copy()
    query_string.pop("page", None)
    categories = list(_store_categories())
    if not any(category.name.casefold() == "pairs" for category in categories):
        categories.append(Category(name="Pairs", slug="pairs"))
    return render(request, "store/shop.html", {
        "products": page_obj.object_list, "page_obj": page_obj,
        "categories": categories,
        "sizes": sorted(sizes, key=str.casefold), "colors": sorted(colors, key=str.casefold),
        "active_cat": cat, "q": q, "sort": sort, "max_price": max_price,
        "active_size": size_filter, "active_color": color_filter,
        "query_string": query_string.urlencode(),
    })


def _comma_token_filter(field, token):
    """Match one trimmed comma-separated value, never a substring of another token."""
    token = token.strip()
    query = Q(**{f"{field}__iexact": token})
    for separator in (",", ", "):
        query |= Q(**{f"{field}__istartswith": f"{token}{separator}"})
        query |= Q(**{f"{field}__iendswith": f"{separator}{token}"})
    for left in (",", ", "):
        for right in (",", ", "):
            query |= Q(**{f"{field}__icontains": f"{left}{token}{right}"})
    return query


def product_detail(request, slug):
    p = get_object_or_404(Product.objects.storefront(), slug=slug)
    recommended_size = None
    size_error = ""
    if request.GET.get("height") or request.GET.get("weight"):
        try:
            height = int(request.GET.get("height", ""))
            weight = int(request.GET.get("weight", ""))
            fit = request.GET.get("fit", "regular")
            if not 120 <= height <= 230 or not 30 <= weight <= 250 or fit not in {"slim", "regular", "relaxed"}:
                raise ValueError
            recommended_size = recommend_size_for(height, weight, fit, p.size_list)
        except (TypeError, ValueError):
            size_error = "Enter a height from 120–230 cm and weight from 30–250 kg."
    category_name = p.category.name.casefold()
    if p.product_type == "trousers" or category_name == "trousers":
        related = Product.objects.storefront().filter(category__name__iexact="Shirts").exclude(pk=p.pk)[:4]
    elif p.product_type == "tracksuit" or category_name in {"tracksuits", "pairs"}:
        related = Product.objects.storefront().filter(category__name__iexact="Shirts").exclude(pk=p.pk)[:4]
    elif p.product_type == "shirt" or category_name == "shirts":
        related = Product.objects.storefront().filter(category__name__iexact="Trousers").exclude(pk=p.pk)[:4]
    else:
        related = Product.objects.none()
    has_complete_look = related.exists()
    if not has_complete_look:
        related = Product.objects.storefront().filter(category=p.category).exclude(pk=p.pk)[:4]
    user_review = None
    can_review = False
    if request.user.is_authenticated:
        user_review = Review.objects.filter(product=p, user=request.user).first()
        can_review = not user_review and Order.objects.filter(
            user=request.user, status="delivered", items__product=p,
        ).exists()
    product_url = request.build_absolute_uri(p.get_absolute_url())
    product_json = {
        "@context": "https://schema.org", "@type": "Product", "name": p.name,
        "description": p.description, "sku": p.slug,
        "image": [request.build_absolute_uri(image.url) for image in p.gallery],
        "offers": {
            "@type": "Offer", "priceCurrency": "PKR", "price": p.price,
            "availability": "https://schema.org/InStock" if p.is_available else "https://schema.org/OutOfStock",
            "url": product_url,
        },
    }
    if p.reviews:
        product_json["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": str(p.rating), "reviewCount": p.reviews}
    json_ld = json.dumps(product_json).replace("<", "\\u003C").replace(">", "\\u003E").replace("&", "\\u0026")
    return render(request, "store/product.html", {
        "p": p, "related": related, "has_complete_look": has_complete_look,
        "approved_reviews": p.customer_reviews.filter(approved=True).select_related("user"),
        "review_form": ReviewForm(), "user_review": user_review, "can_review": can_review,
        "og_image": request.build_absolute_uri(p.image.url) if p.image else "",
        "product_json_ld": mark_safe(json_ld),
        "recommended_size": recommended_size, "size_error": size_error,
    })


@login_required(login_url="store:account")
@require_POST
def submit_review(request, slug):
    product = get_object_or_404(Product.objects.storefront(), slug=slug)
    form = ReviewForm(request.POST)
    if not Order.objects.filter(user=request.user, status="delivered", items__product=product).exists():
        messages.error(request, "A delivered order containing this product is required to leave a review.")
    elif Review.objects.filter(product=product, user=request.user).exists():
        messages.error(request, "You have already reviewed this product.")
    elif form.is_valid():
        try:
            with transaction.atomic():
                Review.objects.create(
                    product=product, user=request.user,
                    rating=form.cleaned_data["rating"], comment=form.cleaned_data["comment"],
                    approved=True,
                )
            messages.success(request, "Your review has been added.")
        except IntegrityError:
            messages.error(request, "You have already reviewed this product.")
    return redirect(product.get_absolute_url())


def search_api(request):
    q = request.GET.get("q", "").strip()
    if not q:
        return JsonResponse({"results": []})
    qs = Product.objects.storefront().filter(Q(name__icontains=q) | Q(category__name__icontains=q) | Q(description__icontains=q))[:6]
    return JsonResponse({"results": [{"name": p.name, "url": p.get_absolute_url(), "image": p.image.url, "price": p.price, "category": p.category.name} for p in qs]})


# ---------------- cart ----------------
def cart_view(request):
    cart = Cart(request)
    return render(request, "store/cart.html", {"lines": cart.lines(), "totals": cart.totals()})


def _record_customer_cart(request, cart):
    if not request.user.is_authenticated:
        return
    if len(cart):
        AbandonedCart.objects.update_or_create(user=request.user, defaults={
            "cart_data": cart.data, "reminded_at": None, "recovered_at": None,
        })
    else:
        AbandonedCart.objects.filter(user=request.user, recovered_at__isnull=True).update(recovered_at=timezone.now())


@require_POST
def cart_add(request, pk):
    p = get_object_or_404(Product.objects.storefront(), pk=pk)
    size = request.POST.get("size", "")
    color = request.POST.get("color", "")
    variant = p.get_variant(size, color)
    if not p.is_available:
        error = f"{p.name} is out of stock."
    elif size not in p.size_list or color not in p.color_list:
        error = "Please choose a valid size and colour."
    elif variant and not variant.active:
        error = "This variant is currently unavailable."
    elif variant and variant.stock_qty <= 0:
        error = "This size and colour is currently out of stock."
    else:
        error = ""
    try:
        qty = max(1, min(int(request.POST.get("qty", 1)), 99))
    except ValueError:
        qty = 1
    cart = Cart(request)
    if not error and cart.add(p, size, color, qty) == 0:
        available_count = p.get_available_stock(size, color)
        error = f"Only {available_count} of {p.name} in {size} / {color} are available."
    if not error:
        _record_customer_cart(request, cart)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        if error:
            return JsonResponse({"ok": False, "message": error, "count": len(cart)}, status=400)
        return JsonResponse({"ok": True, "count": len(cart)})
    if error:
        messages.error(request, error)
        return redirect(p.get_absolute_url())
    messages.success(request, f"{p.name} added to your cart")
    if request.POST.get("buy_now"):
        return redirect("store:checkout")
    next_url = request.POST.get("next", "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("store:cart")


@require_POST
def cart_update(request):
    cart = Cart(request)
    try:
        cart.set_qty(request.POST.get("key", ""), int(request.POST.get("qty", 1)))
    except ValueError:
        pass
    _record_customer_cart(request, cart)
    return redirect("store:cart")


@require_POST
def cart_remove(request):
    cart = Cart(request)
    cart.remove(request.POST.get("key", ""))
    _record_customer_cart(request, cart)
    return redirect("store:cart")


@login_required(login_url="store:account")
def my_orders(request):
    orders = Order.objects.filter(user=request.user).exclude(status="delivered").prefetch_related("items__product")
    request_filter = Q(user=request.user)
    if request.user.email:
        request_filter |= Q(user__isnull=True, email__iexact=request.user.email)
    custom_requests = CustomRequest.objects.filter(request_filter)
    return render(request, "store/my_orders.html", {"orders": orders, "custom_requests": custom_requests})


def checkout(request):
    cart = Cart(request)
    if not cart.lines():
        return redirect("store:cart")
    if not request.user.is_authenticated:
        return redirect(f"{reverse('store:account')}?mode=login&next={reverse('store:checkout')}")
    form = CheckoutForm(request.POST or None, initial={
        "payment_method": "raast",
        "full_name": request.user.get_full_name(),
        "email": request.user.email,
    })
    if request.method == "POST" and form.is_valid():
        payment_method = form.cleaned_data["payment_method"]
        if payment_method == "card" and (not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET):
            messages.error(request, "Stripe card payments are not fully configured yet. Please choose Raast or contact us.")
            return redirect("store:checkout")
        stripe_module = None
        if payment_method == "card":
            try:
                import stripe as stripe_module
            except ImportError:
                messages.error(request, "Stripe support is not installed yet. Please choose Raast or contact us.")
                return redirect("store:checkout")
            stripe_module.api_key = settings.STRIPE_SECRET_KEY
        try:
            with transaction.atomic():
                lines = cart.lines()
                requested = {}
                requested_totals = {}
                for line in lines:
                    key = (line["product"].pk, line["size"], line["color"])
                    requested[key] = requested.get(key, 0) + line["qty"]
                    requested_totals[line["product"].pk] = requested_totals.get(line["product"].pk, 0) + line["qty"]
                locked_products = {
                    product.pk: product
                    for product in Product.objects.storefront().select_for_update().filter(pk__in={key[0] for key in requested}).order_by("pk")
                }
                for (product_id, size, color), qty in requested.items():
                    product = locked_products.get(product_id)
                    if not product or not product.active or not product.in_stock:
                        raise StockUnavailable(f"{product.name if product else 'A cart product'} is unavailable.")
                    if product.stock_qty < requested_totals[product_id]:
                        raise StockUnavailable(f"{product.name}: only {product.stock_qty} total available. Please update your cart.")
                    variant = product.get_variant(size, color)
                    available = variant.stock_qty if variant else product.stock_qty
                    if variant and (not variant.active or available < qty):
                        raise StockUnavailable(f"{product.name} / {size} / {color}: only {available} available. Please update your cart.")
                    if not variant and product.stock_qty < qty:
                        raise StockUnavailable(f"{product.name}: only {product.stock_qty} available. Please update your cart.")

                t = cart.totals()
                order = form.save(commit=False)
                order.user = request.user
                order.payment_method = payment_method
                order.subtotal, order.discount, order.delivery, order.total = t["subtotal"], t["discount"], t["delivery"], t["total"]
                order.save()
                for line in lines:
                    product = locked_products[line["product"].pk]
                    variant = product.get_variant(line["size"], line["color"])
                    item_cost = variant.cost_price if variant and variant.cost_price is not None else product.cost_price
                    OrderItem.objects.create(order=order, product=product, name=product.name, size=line["size"], color=line["color"], price=product.price, cost_price=item_cost, qty=line["qty"])
                for (product_id, size, color), qty in requested.items():
                    product = locked_products[product_id]
                    variant = product.get_variant(size, color)
                    if variant:
                        variant.stock_qty -= qty
                        variant.save(update_fields=["stock_qty"])
                for product_id, qty in requested_totals.items():
                    product = locked_products[product_id]
                    product.stock_qty -= qty
                    product.save(update_fields=["stock_qty"])
                if payment_method == "card":
                    stripe_session = stripe_module.checkout.Session.create(
                        mode="payment",
                        payment_method_types=["card"],
                        client_reference_id=order.number,
                        customer_email=order.email,
                        metadata={"order_number": order.number},
                        line_items=[{
                            "quantity": 1,
                            "price_data": {
                                "currency": "pkr",
                                "unit_amount": order.total * 100,
                                "product_data": {"name": f"MarkX order {order.number}"},
                            },
                        }],
                        success_url=request.build_absolute_uri(
                            reverse("store:order_success", args=[order.number])
                        ) + "?session_id={CHECKOUT_SESSION_ID}",
                        cancel_url=request.build_absolute_uri(reverse("store:checkout")) + "?payment_cancelled=1",
                    )
        except StockUnavailable as exc:
            messages.error(request, str(exc))
            return redirect("store:checkout")
        except Exception as exc:
            if payment_method == "card" and isinstance(exc, stripe_module.StripeError):
                messages.error(request, "Stripe could not start the card payment. Please try again or choose Raast.")
                return redirect("store:checkout")
            raise
        from .notifications import NotificationService
        if payment_method == "cod":
            transaction.on_commit(lambda: NotificationService.notify_new_order(order))
        transaction.on_commit(lambda: NotificationService.notify_store_owner(order))
        if request.user.is_authenticated:
            AbandonedCart.objects.filter(user=request.user, recovered_at__isnull=True).update(recovered_at=timezone.now())
        cart.clear()
        request.session["last_order"] = order.number
        if payment_method == "card":
            return redirect(stripe_session.url)
        if payment_method == "raast":
            return redirect("store:raast_payment", number=order.number)
        return redirect("store:order_success", number=order.number)
    totals = cart.totals()
    return render(request, "store/checkout.html", {
        "form": form, "lines": cart.lines(), "totals": totals,
        "raast_account_title": settings.MARKX.get("RAAST_ACCOUNT_TITLE", ""),
        "raast_iban": settings.MARKX.get("RAAST_IBAN", ""),
    })


def _customer_can_view_order(request, order):
    return (
        order.user_id == getattr(request.user, "pk", None)
        or getattr(request.user, "is_staff", False)
        or request.session.get("last_order") == order.number
    )


def raast_payment(request, number):
    order = get_object_or_404(Order, number=number, payment_method="raast")
    if not _customer_can_view_order(request, order):
        return redirect("store:home")
    qr_url = settings.MARKX.get("RAAST_QR_IMAGE_URL", "").strip()
    return render(request, "store/raast_payment.html", {
        "order": order,
        "qr_available": order.status == "pending",
        "qr_url": qr_url,
        "raast_account_title": settings.MARKX.get("RAAST_ACCOUNT_TITLE", ""),
        "raast_iban": settings.MARKX.get("RAAST_IBAN", ""),
    })


def order_success(request, number):
    order = get_object_or_404(Order.objects.prefetch_related("items__product"), number=number)
    is_owner = request.user.is_authenticated and order.user_id == request.user.pk
    if request.session.get("last_order") != number and not request.user.is_staff and not is_owner:
        return redirect("store:home")
    session_id = request.GET.get("session_id")
    if session_id and order.payment_method == "card" and settings.STRIPE_SECRET_KEY:
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            _mark_stripe_order_paid(session)
            order.refresh_from_db()
        except stripe.StripeError:
            messages.error(request, "We could not verify the card payment yet. Your order status will update after confirmation.")
    return render(request, "store/order_success.html", {
        "order": order,
        "raast_account_title": settings.MARKX.get("RAAST_ACCOUNT_TITLE", ""),
        "raast_iban": settings.MARKX.get("RAAST_IBAN", ""),
    })


def _mark_stripe_order_paid(session):
    order_number = getattr(session, "client_reference_id", None)
    if not order_number or getattr(session, "payment_status", None) != "paid":
        return
    if getattr(session, "currency", None) != "pkr":
        return
    order = Order.objects.filter(number=order_number, payment_method="card", status="pending").first()
    if not order or int(getattr(session, "amount_total", 0) or 0) != order.total * 100:
        return
    order.payment_confirmed = True
    order.status = "confirmed"
    order.save(update_fields=["payment_confirmed", "status"])
    from .notifications import NotificationService
    transaction.on_commit(lambda: NotificationService.notify_new_order(order))


@csrf_exempt
def stripe_webhook(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    if not settings.STRIPE_WEBHOOK_SECRET:
        return HttpResponse(status=503)
    import stripe
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.headers.get("Stripe-Signature", ""), settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return HttpResponse(status=400)
    if event.type == "checkout.session.completed":
        _mark_stripe_order_paid(event.data.object)
    elif event.type == "checkout.session.expired":
        number = getattr(event.data.object, "client_reference_id", None)
        expired_order = Order.objects.filter(number=number, payment_method="card", status="pending").first()
        if expired_order:
            expired_order.status = "cancelled"
            expired_order.save(update_fields=["status"])
    return HttpResponse(status=200)


def track_order(request):
    form = TrackOrderForm(request.POST or None)
    order = None
    if request.method == "POST" and form.is_valid():
        order = Order.objects.filter(
            number__iexact=form.cleaned_data["order_number"].strip(),
            phone=form.cleaned_data["phone"],
        ).first()
        if order is None:
            form.add_error(None, "We could not find an order with those details.")
    return render(request, "store/track.html", {"form": form, "order": order})


@login_required(login_url="store:account")
def wishlist_page(request):
    products = Product.objects.storefront().filter(
        wishlist_entries__user=request.user,
    ).select_related("category").distinct()
    return render(request, "store/wishlist.html", {"products": products})


@login_required(login_url="store:account")
@require_POST
def wishlist_toggle(request, pk):
    product = get_object_or_404(Product.objects.storefront(), pk=pk)
    entry = Wishlist.objects.filter(user=request.user, product=product).first()
    if entry:
        entry.delete()
        in_wishlist = False
    else:
        Wishlist.objects.get_or_create(user=request.user, product=product)
        in_wishlist = True
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "in_wishlist": in_wishlist})
    return redirect("store:wishlist")


@login_required(login_url="store:account")
@require_POST
def wishlist_merge(request):
    try:
        payload = json.loads(request.body or "{}")
        raw_ids = payload.get("ids", []) if isinstance(payload, dict) else []
        product_ids = list({int(value) for value in raw_ids if str(value).isdigit()})[:500]
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "message": "Invalid wishlist data."}, status=400)
    active_ids = Product.objects.storefront().filter(pk__in=product_ids).values_list("pk", flat=True)
    Wishlist.objects.bulk_create(
        [Wishlist(user=request.user, product_id=product_id) for product_id in active_ids],
        ignore_conflicts=True,
    )
    saved_ids = list(
        Wishlist.objects.filter(user=request.user, product__in=Product.objects.storefront())
        .values_list("product_id", flat=True)
    )
    return JsonResponse({"ok": True, "ids": saved_ids})


# ---------------- forms ----------------
def customize(request):
    form = CustomForm(request.POST or None, request.FILES or None, initial={
        "color": "White",
        "custom_text_color": "#111111",
        "name": request.user.get_full_name() if request.user.is_authenticated else "",
        "email": request.user.email if request.user.is_authenticated else "",
    })
    if request.method == "POST" and form.is_valid():
        custom_request = form.save(commit=False)
        custom_request.user = request.user if request.user.is_authenticated else None
        custom_request.save()
        messages.success(request, f"Request #{custom_request.pk} received. You can check its status in My Orders.")
        return redirect("store:customize")
    return render(request, "store/customize.html", {"form": form})


@store_admin_required
@require_POST
def custom_request_status(request, pk, status):
    if status not in dict(CustomRequest.STATUS):
        from django.http import Http404
        raise Http404("Unknown custom request status")
    custom_request = get_object_or_404(CustomRequest, pk=pk)
    custom_request.status = status
    custom_request.save(update_fields=["status"])
    messages.success(request, f"Custom request #{custom_request.pk} marked {status}.")
    return redirect("store:manage_model", model_key="custom-requests")


@store_admin_required
@require_POST
def custom_request_status_update(request, pk):
    custom_request = get_object_or_404(CustomRequest, pk=pk)
    status = request.POST.get("status", "")
    if status not in dict(CustomRequest.STATUS):
        messages.error(request, "Choose a valid custom request status.")
    elif status != custom_request.status:
        custom_request.status = status
        custom_request.save(update_fields=["status"])
        messages.success(request, f"Custom request #{custom_request.pk} marked {custom_request.get_status_display()}.")
    target = reverse("store:manage_model", kwargs={"model_key": "custom-requests"})
    if request.META.get("QUERY_STRING"):
        target += "?" + request.META["QUERY_STRING"]
    return redirect(target)


def bulk_order(request):
    form = BulkForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Bulk quote request received! Our team will reach out within 24 hours.")
        return redirect("store:bulk")
    return render(request, "store/bulk.html", {"form": form})


def contact(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Message sent — thanks for reaching out!")
        return redirect("store:contact")
    return render(request, "store/contact.html", {"form": form})


def about(request):
    return render(request, "store/about.html")


def leave_comment(request):
    initial = {}
    if request.user.is_authenticated:
        initial["name"] = request.user.get_full_name().strip() or request.user.get_username()
    form = CommentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        comment = form.save(commit=False)
        if request.user.is_authenticated:
            comment.user = request.user
        comment.save()
        messages.success(request, "Thanks! Your comment has been added.")
        return redirect("store:about")
    return render(request, "store/comment_form.html", {"form": form})


@login_required
@require_POST
def delete_comment(request, pk):
    comment = get_object_or_404(Comment, pk=pk, user=request.user)
    comment.delete()
    messages.success(request, "Your feedback has been deleted.")
    return redirect("store:account")


@require_POST
def newsletter(request):
    email = request.POST.get("email", "").strip().lower()
    ok = "@" in email and "." in email
    if ok:
        NewsletterSubscriber.objects.get_or_create(email=email)
        send_newsletter_welcome_email(email)
        msg = "Successfully subscribed!"
    else:
        msg = "Please enter a valid email."
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": ok, "message": msg})
    (messages.success if ok else messages.error)(request, msg)
    referer = request.META.get("HTTP_REFERER", "")
    if referer and url_has_allowed_host_and_scheme(
        referer, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return redirect(referer)
    return redirect("store:home")


@store_admin_required
def dashboard(request):
    orders = Order.objects.exclude(status="cancelled")
    low_stock_products = Product.objects.filter(active=True).annotate(
        active_variant_count=Count("variants", filter=Q(variants__active=True)),
        active_variant_stock=Sum("variants__stock_qty", filter=Q(variants__active=True)),
    ).annotate(
        available_stock=Case(
            When(active_variant_count__gt=0, then=F("active_variant_stock")),
            default=F("stock_qty"),
            output_field=IntegerField(),
        ),
    ).filter(available_stock__lt=10)
    low_stock = list(
        low_stock_products.select_related("category").order_by("available_stock", "name")[:10]
    )
    products_missing_cost = Product.objects.filter(cost_price__lte=0).order_by("-created", "name") if request.user.is_superuser else Product.objects.none()
    ctx = {
        "revenue": orders.aggregate(t=Sum("total"))["t"] or 0,
        "orders_count": Order.objects.count(),
        "pending": Order.objects.filter(status="pending").count(),
        "customs": CustomRequest.objects.filter(status="pending").count(),
        "bulks": BulkRequest.objects.filter(status="new").count(),
        "subs": NewsletterSubscriber.objects.count(),
        "messages_n": ContactMessage.objects.filter(handled=False).count(),
        "recent": Order.objects.all()[:10],
        "top": OrderItem.objects.values("name").annotate(n=Sum("qty")).order_by("-n")[:5],
        "low_stock_count": low_stock_products.count(),
        "low_stock": low_stock,
        "products_missing_cost": products_missing_cost[:10],
        "products_missing_cost_count": products_missing_cost.count(),
        "is_owner": request.user.is_superuser,
    }
    return render(request, "store/dashboard.html", ctx)


def _finance_range(request):
    today = timezone.localdate()
    period = request.GET.get("range", "30d")
    if period == "today":
        start = end = today
    elif period == "7d":
        start, end = today - timedelta(days=6), today
    elif period == "month":
        start, end = today.replace(day=1), today
    elif period == "last_month":
        end = today.replace(day=1) - timezone.timedelta(days=1)
        start = end.replace(day=1)
    elif period == "custom":
        start = parse_date(request.GET.get("start", "")) or today.replace(day=1)
        end = parse_date(request.GET.get("end", "")) or today
    else:
        period = "30d"
        start, end = today - timedelta(days=29), today
    return period, start, end


@owner_required
def finance_dashboard(request):
    period, start, end = _finance_range(request)
    orders = list(Order.objects.filter(created__date__gte=start, created__date__lte=end).exclude(status__in=("cancelled", "returned")).prefetch_related("items__product__category"))
    expenses = Expense.objects.filter(date__gte=start, date__lte=end)
    revenue = sum((o.total for o in orders), 0)
    cogs = sum((item.cost_price * item.qty for order in orders for item in order.items.all()), 0)
    gross = sum((order.gross_profit for order in orders), 0)
    expense_total = sum((e.amount for e in expenses), 0)
    net = gross - expense_total
    units = sum(item.qty for order in orders for item in order.items.all())
    by_product = {}
    by_category = {}
    by_day = {}
    for order in orders:
        key = order.created.astimezone(timezone.get_current_timezone()).date().isoformat()
        day = by_day.setdefault(key, {"date": key, "revenue": 0, "profit": 0})
        day["revenue"] += order.total
        day["profit"] += order.gross_profit
        order_items = list(order.items.all())
        order_item_revenue = sum(item.price * item.qty for item in order_items)
        order_adjustments = order.discount + order.shipping_cost
        adjustments_allocated = Decimal("0")
        for item_index, item in enumerate(order_items):
            row = by_product.setdefault(item.name, {"name": item.name, "units": 0, "revenue": 0, "cost": 0, "profit": 0})
            line_revenue = item.price * item.qty
            if item_index == len(order_items) - 1:
                allocated_adjustments = order_adjustments - adjustments_allocated
            else:
                allocated_adjustments = order_adjustments * Decimal(line_revenue) / Decimal(order_item_revenue) if order_item_revenue else Decimal("0")
            adjustments_allocated += allocated_adjustments
            row["units"] += item.qty
            row["revenue"] += line_revenue
            row["cost"] += item.cost_price * item.qty
            item_profit = (item.price - item.cost_price) * item.qty - allocated_adjustments
            row["profit"] += item_profit
            category_name = item.product.category.name.casefold() if item.product_id else ""
            product_type = item.product.product_type.casefold() if item.product_id else ""
            category = "Trousers" if "trouser" in category_name or product_type == "trousers" else "Pairs" if "pair" in category_name or product_type in {"pair", "pairs"} else "Shirts"
            by_category[category] = by_category.get(category, 0) + item_profit
    category_expenses = list(expenses.values("category").annotate(total=Sum("amount")).order_by("category"))
    for row in by_product.values():
        row["margin_pct"] = round(float(row["profit"]) * 100 / row["revenue"], 1) if row["revenue"] else 0
        row["margin_per_piece"] = round(float(row["profit"]) / row["units"], 2) if row["units"] else 0
    low_stock_products = Product.objects.filter(active=True).annotate(
        active_variant_count=Count("variants", filter=Q(variants__active=True)),
        active_variant_stock=Sum("variants__stock_qty", filter=Q(variants__active=True)),
    ).annotate(
        available_stock=Case(When(active_variant_count__gt=0, then=F("active_variant_stock")), default=F("stock_qty"), output_field=IntegerField()),
    ).filter(available_stock__lt=10).prefetch_related("variants").order_by("available_stock", "name")[:10]
    low_stock = []
    for product in low_stock_products:
        variants = [variant for variant in product.variants.all() if variant.active]
        stock_value = sum(((variant.cost_price if variant.cost_price is not None else product.cost_price) * variant.stock_qty for variant in variants), Decimal("0")) if variants else product.cost_price * product.stock_qty
        low_stock.append({"product": product, "value": stock_value})
    context = {
        "period": period, "start": start, "end": end, "revenue": revenue, "cogs": cogs,
        "gross_profit": gross, "expense_total": expense_total, "net_profit": net,
        "margin": round(float(gross) * 100 / revenue, 1) if revenue else 0,
        "orders_count": len(orders), "aov": round(revenue / len(orders), 2) if orders else 0,
        "product_rows": sorted(by_product.values(), key=lambda row: row["profit"], reverse=True),
        "top_products": sorted(by_product.values(), key=lambda row: row["profit"], reverse=True)[:5],
        "daily_json": json.dumps(sorted(by_day.values(), key=lambda row: row["date"]), default=float),
        "expense_json": json.dumps(category_expenses, default=str),
        "category_json": json.dumps([{"category": key, "profit": value} for key, value in by_category.items()], default=float),
        "low_stock": low_stock,
    }
    if request.GET.get("export") == "1":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="finance-report.csv"'
        writer = csv.writer(response)
        writer.writerow(["Metric", "Amount"])
        for label, value in (("Revenue", revenue), ("Cost of goods sold", cogs), ("Gross profit", gross), ("Total expenses", expense_total), ("Net profit", net), ("Margin %", context["margin"]), ("Orders", len(orders)), ("Average order value", context["aov"])):
            writer.writerow([label, value])
        writer.writerow([]); writer.writerow(["Product", "Units", "Revenue", "Cost", "Profit", "Margin %"])
        for row in context["product_rows"]:
            writer.writerow([row["name"], row["units"], row["revenue"], row["cost"], row["profit"], round(row["profit"] * 100 / row["revenue"], 1) if row["revenue"] else 0])
        return response
    return render(request, "store/finance_dashboard.html", context)


def health(request):
    return JsonResponse({"status": "ok"})


@owner_required
def orders_csv(request):
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="orders.csv"'
    writer = csv.writer(response)
    writer.writerow(["Order", "Date", "Customer", "Status", "Subtotal", "Discount", "Delivery", "Total"])
    for order in Order.objects.all():
        writer.writerow([order.number, order.created.isoformat(), order.full_name, order.status, order.subtotal, order.discount, order.delivery, order.total])
    return response


@owner_required
def team(request):
    managers = get_user_model().objects.filter(groups__name="Manager", is_superuser=False).distinct().order_by("username")
    return render(request, "store/team.html", {"managers": managers})


@owner_required
def team_create(request):
    from django.contrib.auth.forms import UserCreationForm
    class ManagerForm(UserCreationForm):
        email = forms.EmailField(required=False)
        class Meta(UserCreationForm.Meta):
            model = get_user_model()
            fields = ("username", "email")
    form = ManagerForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save(commit=False); user.is_staff = True; user.save()
        user.groups.add(Group.objects.get_or_create(name="Manager")[0])
        return redirect("store:team")
    return render(request, "store/team_form.html", {"form": form})


@owner_required
@require_POST
def team_deactivate(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, groups__name="Manager", is_superuser=False)
    user.is_active = False; user.save(update_fields=["is_active"])
    messages.success(request, f"Manager {user.username} deactivated.")
    return redirect("store:team")


@owner_required
@require_POST
def team_activate(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, groups__name="Manager", is_superuser=False)
    user.is_active = True; user.save(update_fields=["is_active"])
    messages.success(request, f"Manager {user.username} activated.")
    return redirect("store:team")


@owner_required
@require_POST
def team_delete(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, groups__name="Manager", is_superuser=False)
    username = user.username
    user.delete()
    messages.success(request, f"Manager {username} deleted.")
    return redirect("store:team")


@owner_required
def team_password(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, groups__name="Manager", is_superuser=False)
    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Manager password updated."); return redirect("store:team")
    return render(request, "store/team_form.html", {"form": form, "password_reset": True, "manager": user})


@store_admin_required
def expenses(request):
    qs = Expense.objects.select_related("created_by")
    start = parse_date(request.GET.get("start", ""))
    end = parse_date(request.GET.get("end", ""))
    category = request.GET.get("category", "")
    if start: qs = qs.filter(date__gte=start)
    if end: qs = qs.filter(date__lte=end)
    if category in dict(Expense.CATEGORIES): qs = qs.filter(category=category)
    month_start = timezone.localdate().replace(day=1)
    month_total = Expense.objects.filter(date__gte=month_start).aggregate(total=Sum("amount"))["total"] or 0
    if request.GET.get("export") == "1":
        if not request.user.is_superuser:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="expenses.csv"'
        writer = csv.writer(response); writer.writerow(["Date", "Category", "Title", "Amount", "Note"])
        for expense in qs: writer.writerow([expense.date, expense.category, expense.title, expense.amount, expense.note])
        return response
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    query_string = request.GET.copy()
    query_string.pop("page", None)
    return render(request, "store/expenses.html", {"page_obj": page, "categories": Expense.CATEGORIES, "selected_category": category, "start": start, "end": end, "month_total": month_total, "can_manage": request.user.is_superuser, "query_string": query_string})


@store_admin_required
def expense_edit(request, pk=None):
    if pk is not None and not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    instance = get_object_or_404(Expense, pk=pk) if pk else None
    form = forms.modelform_factory(Expense, fields=("date", "category", "title", "amount", "note"))(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        if not instance: expense.created_by = request.user
        expense.save()
        return redirect("store:expenses")
    return render(request, "store/expense_form.html", {"form": form, "instance": instance})


@store_admin_required
@require_POST
def expense_delete(request, pk):
    if not request.user.is_superuser:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    get_object_or_404(Expense, pk=pk).delete()
    return redirect("store:expenses")


@store_admin_required
def inventory_csv_import(request):
    errors, preview, token = [], [], ""
    if request.method == "POST" and request.POST.get("action") == "commit":
        try:
            rows = signing.loads(request.POST.get("token", ""), max_age=1800, salt="inventory-csv")
            _validate_inventory_rows(rows)
            with transaction.atomic():
                products = {p.slug: p for p in Product.objects.select_for_update().filter(slug__in={r["product_slug"] for r in rows})}
                for row in rows:
                    ProductVariant.objects.update_or_create(
                        product=products[row["product_slug"]], size=row["size"], color=row["color"],
                        defaults={"stock_qty": int(row["stock_qty"]), "sku": row["sku"], "active": True},
                    )
            messages.success(request, f"Imported {len(rows)} variant inventory rows.")
            return redirect("store:inventory_import")
        except (signing.BadSignature, ValueError, Product.DoesNotExist) as exc:
            errors.append(str(exc) or "The preview expired; upload the CSV again.")
    elif request.method == "POST":
        uploaded = request.FILES.get("csv_file")
        if not uploaded:
            errors.append("Choose a CSV file to preview.")
        elif uploaded.size > 2 * 1024 * 1024:
            errors.append("CSV files must be 2 MB or smaller.")
        else:
            try:
                text = TextIOWrapper(BytesIO(uploaded.read()), encoding="utf-8-sig", newline="")
                reader = csv.DictReader(text)
                required = {"product_slug", "size", "color", "stock_qty"}
                if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
                    errors.append("Required CSV columns: product_slug,size,color,stock_qty (sku is optional).")
                else:
                    rows = [{key: (value or "").strip() for key, value in row.items() if key} for row in reader]
                    errors = _inventory_csv_errors(rows)
                    if not errors:
                        token = signing.dumps(rows, salt="inventory-csv")
                        preview = rows
            except (UnicodeDecodeError, csv.Error):
                errors.append("The file is not a valid UTF-8 CSV.")
    return render(request, "store/inventory_import.html", {"errors": errors, "preview": preview, "token": token})


def _inventory_csv_errors(rows):
    errors = []
    seen = set()
    seen_skus = set()
    slugs = {row.get("product_slug", "") for row in rows}
    products = {p.slug: p for p in Product.objects.filter(slug__in=slugs)}
    known = set(products)
    skus = {row.get("sku", "") for row in rows if row.get("sku", "")}
    existing_skus = set(ProductVariant.objects.filter(sku__in=skus).values_list("sku", flat=True))
    for index, row in enumerate(rows, start=2):
        slug, size, color = row.get("product_slug", ""), row.get("size", ""), row.get("color", "")
        if not slug or slug not in known:
            errors.append(f"Row {index}: unknown or missing product_slug.")
        if not size or len(size) > 10 or not color or len(color) > 30:
            errors.append(f"Row {index}: size and color are required and must be valid.")
        elif slug in products:
            product = products[slug]
            if size.casefold() not in {value.casefold() for value in product.size_list}:
                errors.append(f"Row {index}: size is not configured for this product.")
            if color.casefold() not in {value.casefold() for value in product.color_list}:
                errors.append(f"Row {index}: color is not configured for this product.")
        try:
            quantity = int(row.get("stock_qty", ""))
            if quantity < 0:
                raise ValueError
        except ValueError:
            errors.append(f"Row {index}: stock_qty must be zero or a positive integer.")
        key = (slug, size.casefold(), color.casefold())
        if key in seen:
            errors.append(f"Row {index}: duplicate product/size/color combination.")
        seen.add(key)
        sku = row.get("sku", "")
        if sku and (sku in seen_skus or (sku in existing_skus and not ProductVariant.objects.filter(product__slug=slug, size__iexact=size, color__iexact=color, sku=sku).exists())):
            errors.append(f"Row {index}: duplicate SKU.")
        if sku:
            seen_skus.add(sku)
    return errors


def _validate_inventory_rows(rows):
    errors = _inventory_csv_errors(rows)
    if errors:
        raise ValueError("; ".join(errors))


@store_admin_required
def staff_workspace(request):
    sections = [
        {
            "key": key,
            "title": spec["title"],
            "count": spec["model"].objects.count(),
            "url": reverse("store:manage_model", kwargs={"model_key": key}),
            "can_add": spec.get("can_add", True),
        }
        for key, spec in STAFF_MANAGEMENT_MODELS.items()
        if request.user.is_superuser or key not in {"categories", "subscribers"}
    ]
    return render(request, "store/staff_workspace.html", {"sections": sections})


@store_admin_required
def staff_model_list(request, model_key):
    if not request.user.is_superuser and model_key in {"subscribers", "coupons", "users", "roles"}:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    spec = _staff_management_spec(model_key)
    queryset = spec["model"].objects.all()
    if spec.get("select_related"):
        queryset = queryset.select_related(*spec["select_related"])
    if model_key == "orders":
        queryset = queryset.select_related("payment_confirmed_by")
        queryset = queryset.prefetch_related("items__product__variants")
    queryset = queryset.order_by(*spec["ordering"])
    if model_key == "products" and not request.user.is_superuser:
        spec = {**spec, "columns": tuple((f, label) for f, label in spec["columns"] if f not in {"cost_price", "margin"})}
    filter_choices_by_field = dict(spec["filters"])
    if model_key == "products":
        category_filters = _store_categories()
        filter_choices_by_field["category"] = tuple((category.slug, category.name) for category in category_filters)

    search_query = request.GET.get("q", "").strip()
    if search_query:
        search_filter = Q()
        for field in spec["search_fields"]:
            search_filter |= Q(**{f"{field}__icontains": search_query})
        queryset = queryset.filter(search_filter)

    active_filters = {}
    for field, choices in filter_choices_by_field.items():
        selected = request.GET.get(field, "")
        values = {str(value) for value, _ in choices}
        if selected in values:
            active_filters[field] = selected
            filter_value = selected == "true" if selected in {"true", "false"} else selected
            if model_key == "products" and field == "category":
                if selected == "pairs":
                    queryset = queryset.filter(
                        Q(category__name__iexact="Shirts")
                        | Q(category__name__iexact="Trousers")
                        | Q(category__name__iexact="Pairs")
                    )
                else:
                    queryset = queryset.filter(category__slug=selected)
            else:
                queryset = queryset.filter(**{field: filter_value})

    order_date = request.GET.get("order_date", "") if model_key == "orders" else ""
    parsed_order_date = parse_date(order_date) if order_date else None
    if parsed_order_date:
        queryset = queryset.filter(created__date=parsed_order_date)

    paginator = Paginator(queryset, 10 if model_key == "orders" else 25)
    page = paginator.get_page(request.GET.get("page"))
    rows = [{
        "object": obj,
        "cells": [
            "—" if model_key == "categories" and field == "show_on_home"
            and obj.name.strip().casefold() not in {"shirts", "trousers"}
            else _staff_display_value(obj, field)
            for field, _ in spec["columns"]
        ],
        "image_url": getattr(obj, spec.get("thumbnail_field", "image")).url
        if spec.get("show_thumbnail") and getattr(obj, spec.get("thumbnail_field", "image"))
        and (model_key != "categories" or obj.name.strip().casefold() in {"shirts", "trousers"}) else "",
        "order_products": [
            {
                "has_stock": bool(item.product),
                "stock_qty": next((variant.stock_qty for variant in item.product.variants.all()
                                   if variant.size.casefold() == item.size.casefold()
                                   and variant.color.casefold() == item.color.casefold()), item.product.stock_qty)
                if item.product else None,
            }
            for item in obj.items.all()
        ] if model_key == "orders" else [],
    } for obj in page.object_list]
    filter_fields = []
    for field, choices in filter_choices_by_field.items():
        selected = active_filters.get(field, "")
        filter_fields.append({
            "name": field,
            "label": field.replace("_", " ").title(),
            "options": [
                {"value": value, "label": label, "selected": str(value) == selected}
                for value, label in choices
            ],
        })
    query_string = request.GET.copy()
    query_string.pop("page", None)
    subscriber_emails = ", ".join(
        NewsletterSubscriber.objects.order_by("email").values_list("email", flat=True)
    ) if model_key == "subscribers" else ""
    return render(request, "store/staff_model_list.html", {
        "model_key": model_key,
        "spec": spec,
        "rows": rows,
        "page_obj": page,
        "search_query": search_query,
        "active_filters": active_filters,
        "order_date": order_date,
        "subscriber_emails": subscriber_emails,
        "can_add": spec.get("can_add", True),
        "can_edit": spec.get("can_edit", True),
        "can_delete": spec.get("can_delete", True) and (
            request.user.is_superuser or spec.get("staff_can_delete", False)
        ),
        "filter_fields": filter_fields,
        "status_choices": Order.STATUS if model_key == "orders" else (),
        "custom_request_status_choices": CustomRequest.STATUS if model_key == "custom-requests" else (),
        "query_string": query_string,
        "singular_title": spec["model"]._meta.verbose_name.title(),
        "column_count": len(spec["columns"]) + 1 + int(spec.get("show_thumbnail", False)) + 2 * int(model_key == "orders"),
        "back_url": reverse("store:staff_workspace"),
        "back_label": "Back to dashboard" if model_key == "orders" else "Back to all sections",
    })


@store_admin_required
def order_receipt(request, pk):
    order = get_object_or_404(Order.objects.prefetch_related("items"), pk=pk)
    return render(request, "store/order_receipt_print.html", {"orders": [order], "sheets": [[order]]})


@store_admin_required
def custom_request_receipt(request, pk):
    custom_request = get_object_or_404(CustomRequest, pk=pk, status="resolved")
    return render(request, "store/custom_request_receipt_print.html", {"custom_request": custom_request})


@store_admin_required
@require_POST
def order_status_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    status = request.POST.get("status", "")
    if status not in dict(Order.STATUS):
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Choose a valid order status.", "current_status": order.status}, status=400)
        messages.error(request, "Choose a valid order status.")
    elif order.payment_method == "raast" and status in {"confirmed", "printing", "shipped", "delivered"} and not order.payment_confirmed:
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "Verify the Raast payment before confirming or processing this order.", "current_status": order.status}, status=400)
        messages.error(request, "Verify the Raast payment before confirming or processing this order.")
    elif status != order.status:
        order.status = status
        order._audit_user_id = request.user.pk
        order.save(update_fields=["status"])
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": True, "message": f"Order {order.number} status updated to {order.get_status_display()}.", "current_status": order.status})
        messages.success(request, f"Order {order.number} status updated to {order.get_status_display()}.")
    elif request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"success": True, "message": "Order status is unchanged.", "current_status": order.status})
    target = reverse("store:manage_model", kwargs={"model_key": "orders"})
    if request.META.get("QUERY_STRING"):
        target += "?" + request.META["QUERY_STRING"]
    return redirect(target)

@store_admin_required
@require_POST
def raast_payment_confirm(request, pk):
    with transaction.atomic():
        order = get_object_or_404(Order.objects.select_for_update(), pk=pk)
        if order.payment_method != "raast":
            messages.error(request, "This order does not use Raast.")
        elif order.payment_confirmed:
            messages.info(request, f"Raast payment for {order.number} is already confirmed.")
        elif order.status != "pending":
            messages.error(request, "Only pending Raast orders can be payment-confirmed.")
        else:
            order.payment_confirmed = True
            order.status = "confirmed"
            order.payment_confirmed_by = request.user
            order._audit_user_id = request.user.pk
            order.save(update_fields=["payment_confirmed", "payment_confirmed_by", "status"])
            from .notifications import NotificationService
            transaction.on_commit(lambda: NotificationService.notify_new_order(order))
            messages.success(request, f"Raast payment verified; order {order.number} is now confirmed.")
    target = reverse("store:manage_model", kwargs={"model_key": "orders"})
    if request.META.get("QUERY_STRING"):
        target += "?" + request.META["QUERY_STRING"]
    return redirect(target)


def _filtered_staff_orders(request):
    orders = Order.objects.prefetch_related("items").all()
    search_query = request.GET.get("q", "").strip()
    if search_query:
        orders = orders.filter(
            Q(number__icontains=search_query)
            | Q(full_name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
        )
    status = request.GET.get("status", "")
    if status in dict(Order.STATUS):
        orders = orders.filter(status=status)
    payment_method = request.GET.get("payment_method", "")
    if payment_method in dict(Order.PAYMENT):
        orders = orders.filter(payment_method=payment_method)
    order_date = request.GET.get("order_date", "")
    parsed_order_date = parse_date(order_date) if order_date else None
    if parsed_order_date:
        orders = orders.filter(created__date=parsed_order_date)
    return orders.order_by("created", "id")


def _receipt_sheets(orders):
    """Group orders two per A4 page (each receipt is half an A4 sheet)."""
    orders = list(orders)
    return [orders[i:i + 2] for i in range(0, len(orders), 2)]


def _orders_for_receipt_request(request):
    selected_ids = request.GET.getlist("order_ids") or request.POST.getlist("order_ids")
    if selected_ids:
        valid_ids = [int(value) for value in selected_ids if value.isdigit()]
        return list(Order.objects.prefetch_related("items").filter(pk__in=valid_ids).order_by("created", "id"))
    if request.method == "POST" or "order_ids" in request.GET:
        return []
    return list(_filtered_staff_orders(request))


@store_admin_required
def order_receipts_print(request):
    orders = _orders_for_receipt_request(request)
    pdf_url = reverse("store:order_receipts_pdf")
    if request.method == "POST":
        if orders:
            pdf_url += "?" + "&".join(f"order_ids={order.pk}" for order in orders)
    elif request.META.get("QUERY_STRING"):
        pdf_url += "?" + request.META["QUERY_STRING"]
    return render(request, "store/order_receipt_print.html", {
        "orders": orders, "sheets": _receipt_sheets(orders), "pdf_url": pdf_url,
    })


@store_admin_required
def order_receipts_pdf(request):
    """All filtered order receipts as one A4 PDF, two receipts per page (top and bottom half)."""
    from io import BytesIO
    from django.contrib.staticfiles import finders
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    orders = _orders_for_receipt_request(request)
    page_w, page_h = A4
    half_h = page_h / 2
    red, black, grey = (0x60 / 255, 0x19 / 255, 0x25 / 255), (0, 0, 0), (0.45, 0.45, 0.45)
    logo_path = finders.find("img/logo-color.png")
    logo = ImageReader(logo_path) if logo_path else None
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("MarkX order receipts")

    def clean(text):
        # Helvetica only covers Latin-1; replace anything else so no black boxes are printed.
        return str(text or "").encode("cp1252", "replace").decode("cp1252")

    def clip(text, font, size, width):
        text = clean(text)
        while text and pdf.stringWidth(text, font, size) > width:
            text = text[:-1]
        return text

    def wrap(text, font, size, width):
        lines, line = [], ""
        for word in clean(text).replace("\n", " ").split():
            candidate = f"{line} {word}".strip()
            if pdf.stringWidth(candidate, font, size) <= width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = clip(word, font, size, width)
        if line:
            lines.append(line)
        return lines or [""]

    def draw_receipt(order, top):
        left, right = 12 * mm, page_w - 12 * mm
        y = top - 9 * mm
        if logo:
            pdf.drawImage(logo, left, y - 11 * mm, width=11 * mm * 3.7, height=11 * mm, mask="auto", preserveAspectRatio=True)
        pdf.setFillColorRGB(*red)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawRightString(right, y - 4 * mm, "ORDER RECEIPT")
        pdf.setFillColorRGB(*black)
        pdf.setFont("Helvetica", 10)
        pdf.drawRightString(right, y - 9 * mm, f"# {order.number}")
        y -= 14 * mm
        pdf.setStrokeColorRGB(*red); pdf.setLineWidth(1.5); pdf.line(left, y, right, y)
        col_w = 62 * mm
        # left column: order + customer
        ly = y - 6 * mm
        def heading(text, yy):
            pdf.setFillColorRGB(*red); pdf.setFont("Helvetica-Bold", 8.5); pdf.drawString(left, yy, text.upper())
            pdf.setStrokeColorRGB(0.85, 0.85, 0.85); pdf.setLineWidth(.5); pdf.line(left, yy - 1.5 * mm, left + col_w, yy - 1.5 * mm)
            pdf.setFillColorRGB(*black)
            return yy - 5.5 * mm
        def kv(label, value, yy):
            pdf.setFont("Helvetica", 9); pdf.drawString(left, yy, label)
            pdf.setFont("Helvetica-Bold", 9); pdf.drawRightString(left + col_w, yy, clip(value, "Helvetica-Bold", 9, col_w - 22 * mm))
            return yy - 4.4 * mm
        ly = heading("Order", ly)
        ly = kv("Date", timezone.localtime(order.created).strftime("%d %b %Y, %H:%M"), ly)
        ly = kv("Status", order.get_status_display(), ly)
        ly = kv("Payment", order.get_payment_method_display(), ly)
        ly -= 2 * mm
        ly = heading("Customer", ly)
        pdf.setFont("Helvetica-Bold", 9.5); pdf.drawString(left, ly, clip(order.full_name, "Helvetica-Bold", 9.5, col_w)); ly -= 4.6 * mm
        pdf.setFont("Helvetica", 9)
        for line in [order.phone] + wrap(f"{order.address}, {order.city}".strip(", "), "Helvetica", 9, col_w) + ([order.email] if order.email else []):
            pdf.drawString(left, ly, clip(line, "Helvetica", 9, col_w)); ly -= 4.2 * mm
        if order.notes:
            ly -= 2 * mm
            ly = heading("Notes", ly)
            for line in wrap(order.notes, "Helvetica", 8.5, col_w)[:4]:
                pdf.setFont("Helvetica", 8.5); pdf.drawString(left, ly, line); ly -= 4 * mm
        # right column: items
        rx = left + col_w + 8 * mm
        rw = right - rx
        cols = [rx, rx + rw * .36, rx + rw * .48, rx + rw * .60, rx + rw * .68]  # name,size,colour,qty,price(right edge at .86); amount right-aligned
        ry = y - 6 * mm
        items = list(order.items.all())
        footer_y = top - half_h + 12 * mm
        totals_h = 24 * mm
        avail = ry - footer_y - totals_h - 6 * mm
        row_h = max(3.4 * mm, min(6 * mm, avail / max(len(items), 1)))
        fsize = 8.5 if row_h >= 5 * mm else 7
        pdf.setFillColorRGB(*black); pdf.rect(rx, ry - 4.5 * mm, rw, 5.5 * mm, stroke=0, fill=1)
        pdf.setFillColorRGB(1, 1, 1); pdf.setFont("Helvetica-Bold", 7.5)
        for x, label in zip(cols[:4], ("ITEM", "SIZE", "COLOUR", "QTY")):
            pdf.drawString(x + 1.5 * mm, ry - 3 * mm, label)
        pdf.drawRightString(rx + rw * .79, ry - 3 * mm, "PRICE")
        pdf.drawRightString(right - 1.5 * mm, ry - 3 * mm, "AMOUNT")
        ry -= 5.5 * mm
        pdf.setFillColorRGB(*black)
        for item in items:
            ry -= row_h
            pdf.setFont("Helvetica", fsize)
            pdf.drawString(cols[0] + 1.5 * mm, ry + row_h * .3, clip(item.name, "Helvetica", fsize, cols[1] - cols[0] - 3 * mm))
            pdf.drawString(cols[1] + 1.5 * mm, ry + row_h * .3, clip(item.size, "Helvetica", fsize, cols[2] - cols[1] - 2 * mm))
            pdf.drawString(cols[2] + 1.5 * mm, ry + row_h * .3, clip(item.color, "Helvetica", fsize, cols[3] - cols[2] - 2 * mm))
            pdf.drawString(cols[3] + 1.5 * mm, ry + row_h * .3, str(item.qty))
            pdf.drawRightString(rx + rw * .79, ry + row_h * .3, f"Rs. {item.price:,}")
            pdf.drawRightString(right - 1.5 * mm, ry + row_h * .3, f"Rs. {item.line_total:,}")
            pdf.setStrokeColorRGB(0.88, 0.88, 0.88); pdf.setLineWidth(.4); pdf.line(rx, ry, right, ry)
        ry -= 5 * mm
        tx = right - 62 * mm
        def total_line(label, value, yy, bold=False, size=9):
            pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
            pdf.drawString(tx, yy, label); pdf.drawRightString(right - 1.5 * mm, yy, value)
            return yy - 4.6 * mm
        ry = total_line("Subtotal", f"Rs. {order.subtotal:,}", ry)
        if order.discount:
            ry = total_line("Discount", f"- Rs. {order.discount:,}", ry)
        ry = total_line("Delivery", f"Rs. {order.delivery:,}", ry)
        pdf.setStrokeColorRGB(*black); pdf.setLineWidth(1.2); pdf.line(tx, ry + 2.8 * mm, right, ry + 2.8 * mm)
        pdf.setFillColorRGB(*red)
        total_line("TOTAL", f"Rs. {order.total:,}", ry - 2.2 * mm, True, 13)
        # footer
        pdf.setFillColorRGB(*grey); pdf.setFont("Helvetica", 8)
        pdf.setStrokeColorRGB(0.85, 0.85, 0.85); pdf.setLineWidth(.5); pdf.line(left, top - half_h + 11 * mm, right, top - half_h + 11 * mm)
        pdf.drawString(left, top - half_h + 7 * mm, "Thank you for shopping with MarkX Collection")
        pdf.drawRightString(right, top - half_h + 7 * mm, "Wear your mindset.")
        pdf.setFillColorRGB(*black)

    if not orders:
        pdf.setFont("Helvetica-Bold", 14); pdf.drawCentredString(page_w / 2, page_h / 2, "No matching orders")
        pdf.showPage()
    for index in range(0, len(orders), 2):
        draw_receipt(orders[index], page_h)
        if index + 1 < len(orders):
            draw_receipt(orders[index + 1], half_h)
        pdf.setDash(3, 3); pdf.setStrokeColorRGB(0.5, 0.5, 0.5); pdf.setLineWidth(.5)
        pdf.line(6 * mm, half_h, page_w - 6 * mm, half_h); pdf.setDash()
        pdf.showPage()
    pdf.save()
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="markx-order-receipts-a4.pdf"'
    return response


@store_admin_required
@never_cache
def staff_model_edit(request, model_key, pk=None):
    if not request.user.is_superuser and model_key in {"subscribers", "coupons", "users", "roles"}:
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if not request.user.is_superuser and model_key == "categories" and request.method == "POST":
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    spec = _staff_management_spec(model_key)
    model = spec["model"]
    is_create = pk is None
    if is_create and not spec.get("can_add", True):
        from django.http import Http404
        raise Http404("Adding records is disabled for this section")
    if not is_create and not spec.get("can_edit", True):
        from django.http import Http404
        raise Http404("Editing records is disabled for this section")
    instance = get_object_or_404(model, pk=pk) if pk is not None else None
    form_fields = spec["form_fields"] if instance else [
        field.name for field in model._meta.fields
        if field.editable and not field.primary_key and field.name not in spec.get("excluded_fields", ())
    ]
    if not request.user.is_superuser:
        form_fields = [field for field in form_fields if field not in {"cost_price", "shipping_cost", "payment_confirmed_by"}]
    if isinstance(model, Category) and instance and instance.name.strip().casefold() not in {"shirts", "trousers"}:
        form_fields = [field for field in form_fields if field not in {"image", "show_on_home"}]
    form_class = modelform_factory(model, fields=form_fields)
    form = form_class(request.POST or None, request.FILES or None, instance=instance)
    if is_create and isinstance(model, Product):
        form.fields["category"].queryset = Category.objects.all()
        form.fields["product_type"].choices = (("shirt", "Shirt"), ("trousers", "Trousers"), ("pair", "Pair"))
        form.fields["product_type"].widget = forms.Select(choices=form.fields["product_type"].choices)
        form.fields["sizes"].help_text = "Shirts: S, M, L, XL, XXL. Trousers: 28, 30, 32, 34, 36, 38."
    if isinstance(model, Category) and "image" in form.fields:
        form.fields["image"].help_text = "Upload the cover image shown for this category on the homepage."
    if isinstance(model, Product):
        form.fields.pop("size_guide", None)
        placeholders = {
            "name": "e.g. Classic Oxford Shirt",
            "slug": "e.g. classic-oxford-shirt (leave blank to generate)",
            "description": "Describe the fabric, fit, and key product details.",
            "price": "Enter the selling price in rupees",
            "old_price": "Optional: previous price in rupees",
            "stock_qty": "Enter available stock quantity",
            "colors": "e.g. Black, White, Navy",
            "sizes": "Shirt or trouser sizes, separated by commas",
        }
        for field_name, placeholder in placeholders.items():
            if field_name in form.fields:
                form.fields[field_name].widget.attrs["placeholder"] = placeholder
        form.fields["image"].help_text = "Upload the main product photo shown in the shop."
        form.fields["image2"].help_text = "Optional alternate or back photo."
        form.fields["image3"].help_text = "Optional third product photo."
        if "rating" in form.fields:
            form.fields["rating"].widget.attrs["placeholder"] = "e.g. 4.5"
        if "reviews" in form.fields:
            form.fields["reviews"].widget.attrs["placeholder"] = "e.g. 0"
    if request.method == "POST" and form.is_valid():
        if isinstance(model, Order) and instance and form.cleaned_data.get("status") != instance.status:
            instance._audit_user_id = request.user.pk
        if isinstance(model, Product) and is_create:
            product = form.save(commit=False)
            category_name = product.category.name.strip().casefold()
            product.size_guide = "set" if "pair" in category_name else "bottom" if "trouser" in category_name else "shirt"
            product.save()
            form.save_m2m()
        else:
            form.save()
        action = "created" if is_create else "updated"
        messages.success(request, f"{model._meta.verbose_name.title()} {action}.")
        return redirect("store:manage_model", model_key=model_key)

    readonly_values = []
    if instance:
        readonly_values = [
            (
                model._meta.get_field(field).verbose_name.capitalize(),
                _staff_display_value(instance, field),
                getattr(instance, field).url if getattr(instance, field) and model._meta.get_field(field).get_internal_type() == "ImageField" else "",
            )
            for field in spec.get("readonly_fields", ())
            if field != "payment_confirmed_by" or not request.user.is_superuser
        ]
    image_previews = [
        (field, getattr(instance, field).url)
        for field in ("image", "image2", "image3")
        if isinstance(instance, Product) and getattr(instance, field)
    ] if instance else []
    return render(request, "store/staff_model_form.html", {
        "model_key": model_key,
        "spec": spec,
        "form": form,
        "singular_title": model._meta.verbose_name.title(),
        "instance": instance,
        "is_create": is_create,
        "readonly_values": readonly_values,
        "image_previews": image_previews,
        "order_items": instance.items.select_related("product").all() if isinstance(instance, Order) else (),
        "audit_logs": instance.audit_logs.select_related("user").all() if isinstance(instance, Order) else (),
    })


@store_admin_required
@require_POST
def staff_model_delete(request, model_key, pk):
    spec = _staff_management_spec(model_key)
    if not request.user.is_superuser and not spec.get("staff_can_delete", False):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied
    if not spec.get("can_delete", True):
        from django.http import Http404
        raise Http404("Deleting records is disabled for this section")
    instance = get_object_or_404(spec["model"], pk=pk)
    try:
        instance.delete()
    except ProtectedError:
        messages.error(request, "This record is still in use and cannot be deleted.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": False, "error": "This product is still in use and cannot be deleted."}, status=409)
    else:
        messages.success(request, f"{spec['model']._meta.verbose_name.title()} deleted.")
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": True})
    list_url = reverse("store:manage_model", kwargs={"model_key": model_key})
    if request.GET:
        list_url = f"{list_url}?{request.GET.urlencode()}"
    return redirect(list_url)


def account(request):
    mode = request.GET.get("mode", "login")
    next_url = request.GET.get("next", "")
    if request.method == "POST":
        mode = request.POST.get("account_action", "login")
        next_url = request.POST.get("next", "")

    login_form = EmailAuthenticationForm(request, data=request.POST if request.method == "POST" and mode == "login" else None)
    signup_form = AccountCreationForm(request.POST if request.method == "POST" and mode == "signup" else None)
    if request.method == "POST" and mode == "login" and login_form.is_valid():
        user = login_form.get_user()
        login(request, user)
        messages.success(request, "Welcome back to MarkX.")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("store:dashboard" if user.is_staff or user.is_superuser else "store:home")

    if request.method == "POST" and mode == "signup" and signup_form.is_valid():
        user = signup_form.save()
        own_code = "MX" + secrets.token_hex(4).upper()
        while ReferralCode.objects.filter(code=own_code).exists():
            own_code = "MX" + secrets.token_hex(4).upper()
        ReferralCode.objects.create(owner=user, code=own_code)
        login(request, user)
        messages.success(request, "Your MarkX profile is ready.")
        if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return redirect(next_url)
        return redirect("store:home")

    own_comments = Comment.objects.filter(user=request.user) if request.user.is_authenticated else Comment.objects.none()
    return render(request, "store/account.html", {
        "login_form": login_form, "signup_form": signup_form, "mode": mode,
        "next_url": next_url, "own_comments": own_comments,
    })


def profile_edit(request):
    if not request.user.is_authenticated:
        return redirect(f"{reverse('store:account')}?mode=login&next={reverse('store:profile_edit')}")
    can_change_email = not request.user.is_staff or request.user.is_superuser
    form = AccountProfileForm(request.POST or None, instance=request.user, allow_email=can_change_email)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile details have been updated.")
        return redirect("store:account")
    return render(request, "store/profile_edit.html", {"form": form})


@login_required(login_url="store:account")
def loyalty(request):
    entries = LoyaltyTransaction.objects.filter(user=request.user).select_related("order")
    balance = sum(entries.values_list("points", flat=True))
    referral, _ = ReferralCode.objects.get_or_create(
        owner=request.user,
        defaults={"code": "MX" + secrets.token_hex(4).upper()},
    )
    return render(request, "store/loyalty.html", {"entries": entries, "balance": balance, "referral": referral})


@require_POST
def account_logout(request):
    logout(request)
    messages.success(request, "You have been signed out.")
    return redirect("store:account")

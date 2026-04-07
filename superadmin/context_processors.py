from .models import Restaurant


def superadmin_nav(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    if not request.user.is_superuser:
        return {}
    return {
        "superadmin_nav_restaurants": Restaurant.objects.filter(is_active=True).order_by("name"),
        "superadmin_active_restaurant_id": request.session.get("superadmin_active_restaurant_id"),
    }

from superadmin.models import RestaurantStaff


def get_portal_staff(request):
    if not request.user.is_authenticated or request.user.is_superuser:
        return None
    try:
        profile = request.user.restaurant_profile
    except RestaurantStaff.DoesNotExist:
        return None
    if not profile.is_active or not profile.restaurant.is_active:
        return None
    return profile

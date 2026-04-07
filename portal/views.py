from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LogoutView
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from superadmin.models import Restaurant, RestaurantStaff
from superadmin.utils import current_fiscal_year

from .forms import PortalAuthenticationForm, RestaurantPortalForm
from .utils import get_portal_staff


@require_http_methods(["GET", "POST"])
def portal_login(request):
    staff = get_portal_staff(request)
    if staff is not None:
        return redirect("portal:dashboard")
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("superadmin:dashboard")

    if request.method == "POST":
        form = PortalAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if user.is_superuser:
                messages.info(request, "Platform admins sign in at Superadmin.")
                return redirect("superadmin:login")
            try:
                profile = user.restaurant_profile
            except RestaurantStaff.DoesNotExist:
                messages.error(request, "This user is not linked to a restaurant.")
            else:
                if not profile.is_active:
                    messages.error(request, "Your restaurant access is inactive.")
                elif not profile.restaurant.is_active:
                    messages.error(request, "This restaurant is inactive.")
                else:
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                    next_url = request.GET.get("next")
                    if next_url and url_has_allowed_host_and_scheme(
                        url=next_url,
                        allowed_hosts={request.get_host()},
                        require_https=request.is_secure(),
                    ):
                        return redirect(next_url)
                    return redirect("portal:dashboard")
    else:
        form = PortalAuthenticationForm(request)
    return render(request, "portal/login.html", {"form": form})


class PortalLogoutView(LogoutView):
    next_page = "portal:login"


def dashboard(request):
    staff = get_portal_staff(request)
    if staff is None:
        if request.user.is_authenticated:
            if request.user.is_superuser:
                return redirect("superadmin:dashboard")
            messages.error(request, "Sign in with a restaurant account.")
        return redirect("portal:login")

    restaurant = staff.restaurant
    fy_list = restaurant.fiscal_years.filter(is_active=True).order_by("-start_date")[:12]
    fy_current = current_fiscal_year(restaurant)
    can_edit = staff.role == RestaurantStaff.Role.RESTAURANT_ADMIN

    return render(
        request,
        "portal/dashboard.html",
        {
            "staff": staff,
            "restaurant": restaurant,
            "fiscal_years": fy_list,
            "current_fiscal_year": fy_current,
            "can_edit_restaurant": can_edit,
        },
    )


@require_http_methods(["GET", "POST"])
def restaurant_edit(request):
    staff = get_portal_staff(request)
    if staff is None:
        return redirect("portal:login")
    if staff.role != RestaurantStaff.Role.RESTAURANT_ADMIN:
        messages.error(request, "Only restaurant admins can change outlet details.")
        return redirect("portal:dashboard")

    restaurant = staff.restaurant
    if request.method == "POST":
        form = RestaurantPortalForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            messages.success(request, "Restaurant details saved.")
            return redirect("portal:dashboard")
    else:
        form = RestaurantPortalForm(instance=restaurant)

    return render(
        request,
        "portal/restaurant_edit.html",
        {
            "form": form,
            "staff": staff,
            "restaurant": restaurant,
            "can_edit_restaurant": True,
        },
    )


@login_required
@ensure_csrf_cookie
def inventory_workspace(request):
    restaurant = None
    staff = get_portal_staff(request)
    if staff is not None:
        restaurant = staff.restaurant
    elif request.user.is_superuser:
        rid = request.session.get("superadmin_active_restaurant_id")
        if rid:
            restaurant = Restaurant.objects.filter(pk=rid, is_active=True).first()
    if restaurant is None:
        if request.user.is_superuser:
            messages.info(
                request,
                "Choose an outlet in Superadmin (Scope data), then open Inventory again.",
            )
            return redirect("superadmin:dashboard")
        return redirect("portal:login")

    can_edit_master = request.user.is_superuser or (
        staff is not None and staff.role == RestaurantStaff.Role.RESTAURANT_ADMIN
    )
    can_edit_restaurant = staff is not None and staff.role == RestaurantStaff.Role.RESTAURANT_ADMIN

    return render(
        request,
        "portal/inventory_workspace.html",
        {
            "restaurant": restaurant,
            "staff": staff,
            "can_edit_master": can_edit_master,
            "can_edit_restaurant": can_edit_restaurant,
        },
    )


@login_required
@ensure_csrf_cookie
def menu_management(request):
    restaurant = None
    staff = get_portal_staff(request)
    if staff is not None:
        restaurant = staff.restaurant
    elif request.user.is_superuser:
        rid = request.session.get("superadmin_active_restaurant_id")
        if rid:
            restaurant = Restaurant.objects.filter(pk=rid, is_active=True).first()
    if restaurant is None:
        if request.user.is_superuser:
            messages.info(
                request,
                "Choose an outlet in Superadmin (Scope data), then open Menu again.",
            )
            return redirect("superadmin:dashboard")
        return redirect("portal:login")

    can_edit_menu = request.user.is_superuser or (
        staff is not None and staff.role == RestaurantStaff.Role.RESTAURANT_ADMIN
    )
    can_edit_restaurant = staff is not None and staff.role == RestaurantStaff.Role.RESTAURANT_ADMIN

    return render(
        request,
        "portal/menu_management.html",
        {
            "restaurant": restaurant,
            "staff": staff,
            "can_edit_menu": can_edit_menu,
            "can_edit_restaurant": can_edit_restaurant,
        },
    )

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LogoutView
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .decorators import superadmin_required
from .forms import (
    ActiveRestaurantForm,
    FiscalYearForm,
    RestaurantForm,
    RestaurantStaffForm,
    SuperadminAuthenticationForm,
)
from .models import FiscalYear, Restaurant, RestaurantStaff
from .utils import current_fiscal_year


@require_http_methods(["GET", "POST"])
def superadmin_login(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect("superadmin:dashboard")
    if request.user.is_authenticated and not request.user.is_superuser:
        return redirect("portal:dashboard")
    if request.method == "POST":
        form = SuperadminAuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            if not user.is_superuser:
                messages.error(request, "Only platform superusers can sign in here.")
            else:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                next_url = request.GET.get("next")
                if next_url and url_has_allowed_host_and_scheme(
                    url=next_url,
                    allowed_hosts={request.get_host()},
                    require_https=request.is_secure(),
                ):
                    return redirect(next_url)
                return redirect("superadmin:dashboard")
    else:
        form = SuperadminAuthenticationForm(request)
    return render(request, "superadmin/login.html", {"form": form})


class SuperadminLogoutView(LogoutView):
    next_page = "superadmin:login"


@superadmin_required
def dashboard(request):
    ctx = {
        "restaurant_count": Restaurant.objects.count(),
        "active_restaurant_count": Restaurant.objects.filter(is_active=True).count(),
        "staff_count": RestaurantStaff.objects.filter(is_active=True).count(),
        "fy_count": FiscalYear.objects.filter(is_active=True).count(),
    }
    return render(request, "superadmin/dashboard.html", ctx)


@superadmin_required
def restaurant_list(request):
    restaurants = Restaurant.objects.all().order_by("name")
    return render(request, "superadmin/restaurant_list.html", {"restaurants": restaurants})


@superadmin_required
@require_http_methods(["GET", "POST"])
def restaurant_create(request):
    if request.method == "POST":
        form = RestaurantForm(request.POST)
        if form.is_valid():
            r = form.save()
            messages.success(request, f"Restaurant “{r.name}” created.")
            return redirect("superadmin:restaurant_detail", slug=r.slug)
    else:
        form = RestaurantForm()
    return render(request, "superadmin/restaurant_form.html", {"form": form, "title": "New restaurant"})


@superadmin_required
def restaurant_detail(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    staff = restaurant.staff_members.select_related("user").order_by("user__username")
    fiscal_years = restaurant.fiscal_years.all()
    fy_current = current_fiscal_year(restaurant)
    return render(
        request,
        "superadmin/restaurant_detail.html",
        {
            "restaurant": restaurant,
            "staff_members": staff,
            "fiscal_years": fiscal_years,
            "current_fiscal_year": fy_current,
        },
    )


@superadmin_required
@require_http_methods(["GET", "POST"])
def restaurant_edit(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.method == "POST":
        form = RestaurantForm(request.POST, instance=restaurant)
        if form.is_valid():
            form.save()
            messages.success(request, "Restaurant updated.")
            return redirect("superadmin:restaurant_detail", slug=restaurant.slug)
    else:
        form = RestaurantForm(instance=restaurant)
    return render(
        request,
        "superadmin/restaurant_form.html",
        {"form": form, "title": f"Edit {restaurant.name}", "restaurant": restaurant},
    )


@superadmin_required
@require_http_methods(["GET", "POST"])
def fiscal_year_create(request, slug):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.method == "POST":
        form = FiscalYearForm(request.POST)
        if form.is_valid():
            fy = form.save(commit=False)
            fy.restaurant = restaurant
            try:
                fy.save()
            except Exception as e:
                messages.error(request, str(e))
            else:
                messages.success(request, f"Fiscal year “{fy.label}” saved.")
                return redirect("superadmin:restaurant_detail", slug=slug)
    else:
        form = FiscalYearForm()
    return render(
        request,
        "superadmin/fiscal_year_form.html",
        {"form": form, "restaurant": restaurant, "title": "New fiscal year"},
    )


@superadmin_required
@require_http_methods(["GET", "POST"])
def fiscal_year_edit(request, slug, pk):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    fy = get_object_or_404(FiscalYear, pk=pk, restaurant=restaurant)
    if request.method == "POST":
        form = FiscalYearForm(request.POST, instance=fy)
        if form.is_valid():
            try:
                form.save()
            except Exception as e:
                messages.error(request, str(e))
            else:
                messages.success(request, "Fiscal year updated.")
                return redirect("superadmin:restaurant_detail", slug=slug)
    else:
        form = FiscalYearForm(instance=fy)
    return render(
        request,
        "superadmin/fiscal_year_form.html",
        {"form": form, "restaurant": restaurant, "fiscal_year": fy, "title": f"Edit {fy.label}"},
    )


@superadmin_required
@require_http_methods(["GET", "POST"])
def staff_create(request, slug):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    restaurant = get_object_or_404(Restaurant, slug=slug)
    if request.method == "POST":
        form = RestaurantStaffForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=form.cleaned_data.get("email") or "",
                password=form.cleaned_data["password1"],
            )
            user.is_staff = False
            user.is_superuser = False
            user.save()
            RestaurantStaff.objects.create(
                user=user,
                restaurant=restaurant,
                role=form.cleaned_data["role"],
            )
            messages.success(request, f"User {user.username} can now sign in for this restaurant.")
            return redirect("superadmin:restaurant_detail", slug=slug)
    else:
        form = RestaurantStaffForm()
    return render(
        request,
        "superadmin/staff_form.html",
        {"form": form, "restaurant": restaurant, "title": "Add restaurant user"},
    )


@superadmin_required
@require_POST
def staff_toggle_active(request, slug, pk):
    restaurant = get_object_or_404(Restaurant, slug=slug)
    profile = get_object_or_404(RestaurantStaff, pk=pk, restaurant=restaurant)
    profile.is_active = not profile.is_active
    profile.save(update_fields=["is_active"])
    messages.info(
        request,
        f"{profile.user.username} is now {'active' if profile.is_active else 'inactive'}.",
    )
    return redirect("superadmin:restaurant_detail", slug=slug)


@superadmin_required
@require_POST
def set_active_restaurant_filter(request):
    form = ActiveRestaurantForm(request.POST)
    if form.is_valid():
        r = form.cleaned_data["restaurant"]
        if r is None:
            request.session.pop("superadmin_active_restaurant_id", None)
            messages.info(request, "Restaurant filter cleared.")
        else:
            request.session["superadmin_active_restaurant_id"] = r.pk
            messages.info(request, f"Filtering as: {r.name}")
    return redirect(request.POST.get("next") or "superadmin:dashboard")

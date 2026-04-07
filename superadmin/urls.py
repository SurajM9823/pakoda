from django.urls import path

from . import views

app_name = "superadmin"

urlpatterns = [
    path("login/", views.superadmin_login, name="login"),
    path("logout/", views.SuperadminLogoutView.as_view(), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("restaurants/", views.restaurant_list, name="restaurant_list"),
    path("restaurants/new/", views.restaurant_create, name="restaurant_create"),
    path("restaurants/<slug:slug>/", views.restaurant_detail, name="restaurant_detail"),
    path("restaurants/<slug:slug>/edit/", views.restaurant_edit, name="restaurant_edit"),
    path(
        "restaurants/<slug:slug>/fiscal-years/new/",
        views.fiscal_year_create,
        name="fiscal_year_create",
    ),
    path(
        "restaurants/<slug:slug>/fiscal-years/<int:pk>/edit/",
        views.fiscal_year_edit,
        name="fiscal_year_edit",
    ),
    path(
        "restaurants/<slug:slug>/staff/new/",
        views.staff_create,
        name="staff_create",
    ),
    path(
        "restaurants/<slug:slug>/staff/<int:pk>/toggle/",
        views.staff_toggle_active,
        name="staff_toggle_active",
    ),
    path("set-restaurant-filter/", views.set_active_restaurant_filter, name="set_restaurant_filter"),
]

from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = "portal"

urlpatterns = [
    path("login/", views.portal_login, name="login"),
    path("logout/", LogoutView.as_view(next_page="portal:login"), name="logout"),
    path("", views.dashboard, name="dashboard"),
    path("restaurant/edit/", views.restaurant_edit, name="restaurant_edit"),
    path("inventory/", views.inventory_workspace, name="inventory"),
    path("menu/", views.menu_management, name="menu"),
]

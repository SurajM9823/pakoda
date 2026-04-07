from django.urls import include, path

from .views import categories_view, health_view, products_view


urlpatterns = [
    path("health/", health_view, name="health"),
    path("categories/", categories_view, name="categories"),
    path("products/", products_view, name="products"),
    path("inventory/", include("inventory.urls")),
    path("menu/", include("menu.urls")),
]

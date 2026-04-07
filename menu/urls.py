from django.urls import path

from . import api

urlpatterns = [
    path("public/", api.menu_public_catalog_view, name="menu_public_catalog"),
    path("categories/", api.menu_categories_view, name="menu_categories"),
    path("categories/<int:pk>/", api.menu_category_detail_view, name="menu_category_detail"),
    path("categories/<int:pk>/image/", api.menu_category_image_view, name="menu_category_image"),
    path("items/", api.menu_items_view, name="menu_items"),
    path("items/<int:pk>/", api.menu_item_detail_view, name="menu_item_detail"),
    path("items/<int:pk>/image/", api.menu_item_image_view, name="menu_item_image"),
    path("items/<int:pk>/ingredients/", api.menu_item_ingredients_view, name="menu_item_ingredients"),
    path(
        "items/<int:pk>/ingredients/<int:ing_pk>/",
        api.menu_item_ingredient_detail_view,
        name="menu_item_ingredient_detail",
    ),
]

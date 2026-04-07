from django.contrib import admin

from .models import MenuCategory, MenuItem, MenuItemIngredient


class MenuItemIngredientInline(admin.TabularInline):
    model = MenuItemIngredient
    extra = 0
    autocomplete_fields = ["master_item"]


@admin.register(MenuCategory)
class MenuCategoryAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "restaurant", "sort_order", "is_active"]
    list_filter = ["restaurant", "is_active"]
    search_fields = ["name"]


@admin.register(MenuItem)
class MenuItemAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "category", "portion_label", "sell_price", "is_active"]
    list_filter = ["category__restaurant", "is_active"]
    search_fields = ["name", "category__name"]
    inlines = [MenuItemIngredientInline]


@admin.register(MenuItemIngredient)
class MenuItemIngredientAdmin(admin.ModelAdmin):
    list_display = ["id", "menu_item", "master_item", "quantity"]
    autocomplete_fields = ["menu_item", "master_item"]

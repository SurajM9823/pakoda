from django.contrib import admin

from .models import FiscalYear, Restaurant, RestaurantStaff


@admin.register(Restaurant)
class RestaurantAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ("name",)}


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ["label", "restaurant", "start_date", "end_date", "is_active"]
    list_filter = ["is_active", "restaurant"]
    search_fields = ["label", "restaurant__name"]


@admin.register(RestaurantStaff)
class RestaurantStaffAdmin(admin.ModelAdmin):
    list_display = ["user", "restaurant", "role", "is_active", "created_at"]
    list_filter = ["is_active", "role", "restaurant"]
    search_fields = ["user__username", "restaurant__name"]
    raw_id_fields = ["user"]

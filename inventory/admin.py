from django.contrib import admin

from .models import Bill, BillLine, MasterItem, RestaurantSequence, Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "restaurant", "phone", "is_active"]
    list_filter = ["restaurant", "is_active"]
    search_fields = ["name"]


class BillLineInline(admin.TabularInline):
    model = BillLine
    extra = 0


@admin.register(MasterItem)
class MasterItemAdmin(admin.ModelAdmin):
    list_display = ["product_num", "name", "restaurant", "cp", "sp", "unit_type", "is_active"]
    list_filter = ["restaurant", "unit_type", "is_active"]
    search_fields = ["name", "product_num"]


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = [
        "bill_code",
        "display_reference",
        "restaurant",
        "vendor",
        "bill_kind",
        "status",
        "is_paid",
        "discount_amount",
        "amount_paid",
        "occurred_at",
    ]
    list_filter = ["bill_kind", "status", "is_paid", "restaurant"]
    inlines = [BillLineInline]
    readonly_fields = ["seq", "bill_code"]


@admin.register(RestaurantSequence)
class RestaurantSequenceAdmin(admin.ModelAdmin):
    list_display = ["restaurant", "next_product_num", "next_bill_seq"]

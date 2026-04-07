from django.urls import path

from . import api

urlpatterns = [
    path("meta/", api.meta_view, name="inventory_meta"),
    path("vendors/", api.vendor_list_create, name="inventory_vendors"),
    path("cash-summary/", api.cash_summary_view, name="inventory_cash_summary"),
    path("vendor-open-bills/", api.vendor_open_bills_view, name="inventory_vendor_open_bills"),
    path("vendor-balances/", api.vendor_balances_view, name="inventory_vendor_balances"),
    path("vendor-payments/", api.vendor_payment_list_create, name="inventory_vendor_payments"),
    path("supplier-ledger/", api.supplier_ledger_view, name="inventory_supplier_ledger"),
    path("return-item-search/", api.return_item_search_view, name="inventory_return_item_search"),
    path("public-menu/", api.public_menu_view, name="inventory_public_menu"),
    path("master-items/", api.master_item_list_create, name="inventory_master_list"),
    path("master-items/quick/", api.master_quick_create, name="inventory_master_quick"),
    path("master-items/<int:pk>/", api.master_item_detail, name="inventory_master_detail"),
    path("master-items/<int:pk>/image/", api.master_item_image_upload, name="inventory_master_image"),
    path("stock-summary/", api.stock_summary, name="inventory_stock_summary"),
    path("stock-incoming/", api.stock_incoming_view, name="inventory_stock_incoming"),
    path("ingredient-uses/", api.ingredient_uses_view, name="inventory_ingredient_uses"),
    path("bills/", api.bill_list_create, name="inventory_bill_list"),
    path("bills/<int:pk>/", api.bill_detail, name="inventory_bill_detail"),
    path("bills/<int:pk>/lines/", api.bill_line_create, name="inventory_bill_line_create"),
    path("bills/<int:pk>/lines/<int:line_id>/", api.bill_line_delete, name="inventory_bill_line_delete"),
]

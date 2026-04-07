from decimal import Decimal

from rest_framework import serializers

from superadmin.utils import current_fiscal_year

from .models import Bill, BillLine, MasterItem, Vendor, VendorPayment, VendorPaymentAllocation, stock_quantity_for_item
from .services import (
    INGREDIENT_USE_REASONS,
    bill_balance_due,
    bill_net_payable,
    bill_subtotal,
    money2,
    qty2,
    unit_pricing_for_master_item,
)


class MasterItemSerializer(serializers.ModelSerializer):
    stock_on_hand = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    pricing = serializers.SerializerMethodField()

    class Meta:
        model = MasterItem
        fields = [
            "id",
            "product_num",
            "name",
            "cp",
            "sp",
            "unit_type",
            "pieces_per_pack",
            "sp_per_piece",
            "notes",
            "is_active",
            "is_sold_as_menu",
            "is_used_as_ingredient",
            "show_on_public_site",
            "image_url",
            "stock_on_hand",
            "pricing",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "product_num", "created_at", "updated_at", "stock_on_hand", "image_url", "pricing"]

    def get_pricing(self, obj):
        return unit_pricing_for_master_item(obj)

    def get_stock_on_hand(self, obj):
        return qty2(stock_quantity_for_item(obj))

    def get_image_url(self, obj):
        if not obj.image:
            return None
        request = self.context.get("request")
        url = obj.image.url
        if request:
            return request.build_absolute_uri(url)
        return url

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["cp"] = money2(instance.cp)
        data["sp"] = money2(instance.sp)
        return data


class MasterItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MasterItem
        fields = [
            "name",
            "cp",
            "sp",
            "unit_type",
            "pieces_per_pack",
            "sp_per_piece",
            "notes",
            "is_active",
            "is_sold_as_menu",
            "is_used_as_ingredient",
            "show_on_public_site",
        ]

    def validate(self, attrs):
        data = super().validate(attrs)
        inst = self.instance
        ut = data.get("unit_type", getattr(inst, "unit_type", None))
        sppp = data.get("sp_per_piece", getattr(inst, "sp_per_piece", False))
        if sppp and ut != MasterItem.UnitType.PACKED:
            raise serializers.ValidationError(
                {"sp_per_piece": "Only valid when unit type is Packed."}
            )
        return data


class VendorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "name", "phone", "notes", "is_active"]


class BillLineSerializer(serializers.ModelSerializer):
    master_item_name = serializers.CharField(source="master_item.name", read_only=True)
    master_product_num = serializers.IntegerField(source="master_item.product_num", read_only=True)
    line_cost_total = serializers.SerializerMethodField()

    class Meta:
        model = BillLine
        fields = [
            "id",
            "master_item",
            "master_item_name",
            "master_product_num",
            "quantity",
            "unit_cp",
            "unit_sp",
            "movement",
            "note",
            "line_cost_total",
        ]
        read_only_fields = ["id", "movement", "line_cost_total"]

    def get_line_cost_total(self, obj):
        return money2(obj.line_cost_total)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["quantity"] = qty2(instance.quantity)
        data["unit_cp"] = money2(instance.unit_cp)
        data["unit_sp"] = money2(instance.unit_sp)
        return data


class BillSerializer(serializers.ModelSerializer):
    lines = BillLineSerializer(many=True, read_only=True)
    display_reference = serializers.CharField(read_only=True)
    vendor_name = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    net_payable = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()

    class Meta:
        model = Bill
        fields = [
            "id",
            "seq",
            "bill_code",
            "display_reference",
            "bill_kind",
            "status",
            "is_paid",
            "vendor",
            "vendor_name",
            "discount_amount",
            "amount_paid",
            "paid_cash",
            "paid_bank",
            "paid_esewa",
            "subtotal",
            "net_payable",
            "balance_due",
            "supplier_reference",
            "notes",
            "occurred_at",
            "fiscal_year",
            "lines",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "seq",
            "bill_code",
            "display_reference",
            "subtotal",
            "net_payable",
            "balance_due",
            "vendor_name",
            "created_at",
        ]

    def get_vendor_name(self, obj):
        return obj.vendor.name if obj.vendor_id else ""

    def get_subtotal(self, obj):
        return money2(bill_subtotal(obj))

    def get_net_payable(self, obj):
        return money2(bill_net_payable(obj))

    def get_balance_due(self, obj):
        return money2(bill_balance_due(obj))

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["discount_amount"] = money2(instance.discount_amount)
        data["amount_paid"] = money2(instance.amount_paid)
        data["paid_cash"] = money2(instance.paid_cash)
        data["paid_bank"] = money2(instance.paid_bank)
        data["paid_esewa"] = money2(instance.paid_esewa)
        return data


class BillCreateSerializer(serializers.Serializer):
    bill_kind = serializers.ChoiceField(choices=Bill.BillKind.choices, default=Bill.BillKind.PURCHASE)
    supplier_reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    vendor_id = serializers.IntegerField(required=False, allow_null=True)


class BillLineCreateSerializer(serializers.Serializer):
    master_item_id = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4)
    unit_cp = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("0"))
    unit_sp = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default=Decimal("0"))
    note = serializers.CharField(required=False, allow_blank=True)
    movement = serializers.ChoiceField(choices=BillLine.Movement.choices, required=False)

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be positive.")
        return value


class VendorPaymentAllocationReadSerializer(serializers.ModelSerializer):
    bill_reference = serializers.CharField(source="bill.display_reference", read_only=True)
    bill_code = serializers.CharField(source="bill.bill_code", read_only=True)

    class Meta:
        model = VendorPaymentAllocation
        fields = ["id", "bill", "bill_code", "bill_reference", "amount"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["amount"] = money2(instance.amount)
        return data


class VendorPaymentSerializer(serializers.ModelSerializer):
    allocations = VendorPaymentAllocationReadSerializer(many=True, read_only=True)
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)

    class Meta:
        model = VendorPayment
        fields = [
            "id",
            "payment_code",
            "vendor",
            "vendor_name",
            "total_amount",
            "paid_cash",
            "paid_bank",
            "paid_esewa",
            "notes",
            "occurred_at",
            "fiscal_year",
            "allocations",
            "created_at",
        ]
        read_only_fields = ["id", "payment_code", "created_at", "vendor_name", "allocations"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["total_amount"] = money2(instance.total_amount)
        data["paid_cash"] = money2(instance.paid_cash)
        data["paid_bank"] = money2(instance.paid_bank)
        data["paid_esewa"] = money2(instance.paid_esewa)
        return data


class VendorPaymentCreateSerializer(serializers.Serializer):
    vendor_id = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    paid_cash = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0")
    )
    paid_bank = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0")
    )
    paid_esewa = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, allow_null=True, min_value=Decimal("0")
    )
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)
    allocations = serializers.ListField(
        child=serializers.DictField(),
        min_length=1,
    )

    def validate_allocations(self, rows):
        out = []
        for r in rows:
            bid = r.get("bill_id")
            amt = r.get("amount")
            if bid is None or amt is None:
                raise serializers.ValidationError("Each allocation needs bill_id and amount.")
            out.append({"bill_id": int(bid), "amount": Decimal(str(amt))})
        return out


class BillUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Bill.Status.choices, required=False)
    is_paid = serializers.BooleanField(required=False)
    supplier_reference = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    occurred_at = serializers.DateTimeField(required=False)
    vendor_id = serializers.IntegerField(required=False, allow_null=True)
    discount_amount = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0")
    )
    amount_paid = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0")
    )
    paid_cash = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0")
    )
    paid_bank = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0")
    )
    paid_esewa = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, min_value=Decimal("0")
    )


class IngredientUseCreateSerializer(serializers.Serializer):
    master_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    reason = serializers.ChoiceField(choices=[(c[0], c[1]) for c in INGREDIENT_USE_REASONS])
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class IngredientUseBatchLineSerializer(serializers.Serializer):
    master_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    note = serializers.CharField(required=False, allow_blank=True, default="")


class IngredientUseBatchCreateSerializer(serializers.Serializer):
    lines = serializers.ListField(
        child=IngredientUseBatchLineSerializer(),
        min_length=1,
        max_length=50,
    )
    reason = serializers.ChoiceField(choices=[(c[0], c[1]) for c in INGREDIENT_USE_REASONS])
    notes = serializers.CharField(required=False, allow_blank=True, default="")

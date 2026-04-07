from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Sum
from django.utils import timezone

from superadmin.models import FiscalYear, Restaurant


class Vendor(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="vendors",
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=64, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RestaurantSequence(models.Model):
    restaurant = models.OneToOneField(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="inventory_sequence",
    )
    next_product_num = models.PositiveIntegerField(default=1)
    next_bill_seq = models.PositiveIntegerField(default=1)
    next_vendor_payment_seq = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f"Seq {self.restaurant_id}"


class MasterItem(models.Model):
    class UnitType(models.TextChoices):
        LITER = "liter", "Liter / liquid"
        PACKED = "packed", "Packed (cigarettes, bread, etc.)"
        PIECE = "piece", "Piece / count"
        KG = "kg", "Kg (vegetables, bulk)"
        VEGETABLE = "vegetable", "Vegetables"
        INGREDIENT = "ingredient", "Kitchen ingredient"
        OTHER = "other", "Other"

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="master_items",
    )
    product_num = models.PositiveIntegerField(
        editable=False,
        db_index=True,
        default=1,
        help_text="Auto-increment per restaurant (overwritten on create).",
    )
    name = models.CharField(max_length=255)
    cp = models.DecimalField(
        "Cost price (CP)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    sp = models.DecimalField(
        "Selling price (SP)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    unit_type = models.CharField(
        max_length=20,
        choices=UnitType.choices,
        default=UnitType.PIECE,
    )
    pieces_per_pack = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="For packed goods: units per pack (e.g. 20 sticks).",
    )
    sp_per_piece = models.BooleanField(
        default=False,
        help_text="Packed items only: if True, SP is per piece; CP stays per pack. If False, SP is per pack like CP.",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    is_sold_as_menu = models.BooleanField(
        default=False,
        help_text="Sold to customers as a menu product (not only kitchen use).",
    )
    is_used_as_ingredient = models.BooleanField(
        default=True,
        help_text="Used in kitchen / recipes / prep.",
    )
    show_on_public_site = models.BooleanField(
        default=True,
        help_text="When sold as menu, whether this item appears on the public menu API.",
    )
    image = models.ImageField(
        upload_to="inventory/products/%Y/%m/",
        blank=True,
        null=True,
        help_text="One photo per product (menu / stock reference).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["restaurant", "product_num"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "product_num"],
                name="inventory_masteritem_unique_product_num",
            ),
        ]
        indexes = [
            models.Index(fields=["restaurant", "name"]),
        ]

    def __str__(self):
        return f"#{self.product_num} {self.name}"

    def clean(self):
        super().clean()
        if self.sp_per_piece and self.unit_type != self.UnitType.PACKED:
            raise ValidationError(
                {"sp_per_piece": "“SP per piece” applies only when unit type is Packed."}
            )

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.product_num = self._allocate_product_num()
        super().save(*args, **kwargs)

    def _allocate_product_num(self) -> int:
        with transaction.atomic():
            seq, _ = RestaurantSequence.objects.select_for_update().get_or_create(
                restaurant=self.restaurant,
                defaults={
                    "next_product_num": 1,
                    "next_bill_seq": 1,
                    "next_vendor_payment_seq": 1,
                },
            )
            n = seq.next_product_num
            seq.next_product_num = n + 1
            seq.save(update_fields=["next_product_num"])
            return n


class Bill(models.Model):
    class BillKind(models.TextChoices):
        PURCHASE = "purchase", "Receiving / purchase"
        PURCHASE_RETURN = "purchase_return", "Return to supplier"
        SALE = "sale", "Sale / issue"
        ADJUSTMENT = "adjustment", "Stock adjustment"

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"
        PAID = "paid", "Paid / settled"

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="inventory_bills",
    )
    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_bills",
    )
    seq = models.PositiveIntegerField(editable=False, db_index=True)
    bill_code = models.CharField(max_length=32, editable=False, db_index=True)
    bill_kind = models.CharField(
        max_length=20,
        choices=BillKind.choices,
        default=BillKind.PURCHASE,
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    is_paid = models.BooleanField(
        default=False,
        help_text="When True, reference shows PA- prefix for unified bill display.",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bills",
    )
    discount_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Vendor discount on this bill (reduces what you owe).",
    )
    amount_paid = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Cash/bank paid to vendor for this bill (can be partial; rest is credit).",
    )
    paid_cash = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Part of amount_paid from cash (purchase: out; return: refund received in cash).",
    )
    paid_bank = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Part of amount_paid via bank transfer.",
    )
    paid_esewa = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        help_text="Part of amount_paid via eSewa / wallet.",
    )
    supplier_reference = models.CharField(
        max_length=120,
        blank=True,
        help_text="Vendor bill / external reference when receiving.",
    )
    notes = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_inventory_bills",
    )

    class Meta:
        ordering = ["-occurred_at", "-seq"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "bill_code"],
                name="inventory_bill_unique_code_per_restaurant",
            ),
        ]

    def __str__(self):
        return self.display_reference

    @property
    def display_reference(self) -> str:
        if self.is_paid:
            return f"PA-{self.bill_code}"
        return self.bill_code

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if is_new:
            self.seq, self.bill_code = self._allocate_bill_code()
        super().save(*args, **kwargs)

    def _allocate_bill_code(self):
        with transaction.atomic():
            seq, _ = RestaurantSequence.objects.select_for_update().get_or_create(
                restaurant=self.restaurant,
                defaults={
                    "next_product_num": 1,
                    "next_bill_seq": 1,
                    "next_vendor_payment_seq": 1,
                },
            )
            n = seq.next_bill_seq
            seq.next_bill_seq = n + 1
            seq.save(update_fields=["next_bill_seq"])
            code = f"B{self.restaurant_id}-{n:07d}"
            return n, code


class BillLine(models.Model):
    class Movement(models.TextChoices):
        ADD = "add", "In / add"
        REMOVE = "remove", "Out / remove"

    bill = models.ForeignKey(
        Bill,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    master_item = models.ForeignKey(
        MasterItem,
        on_delete=models.PROTECT,
        related_name="bill_lines",
    )
    quantity = models.DecimalField(max_digits=14, decimal_places=4)
    unit_cp = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    unit_sp = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    movement = models.CharField(
        max_length=10,
        choices=Movement.choices,
        default=Movement.ADD,
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.bill.bill_code} · {self.master_item.name}"

    def clean(self):
        if self.quantity is not None and self.quantity <= 0:
            raise ValidationError("Quantity must be positive.")
        if not self.bill_id:
            return
        kind = self.bill.bill_kind
        if kind == Bill.BillKind.PURCHASE and self.movement != self.Movement.ADD:
            raise ValidationError("Purchase lines must add stock.")
        if kind == Bill.BillKind.PURCHASE_RETURN and self.movement != self.Movement.REMOVE:
            raise ValidationError("Return lines must remove stock.")
        if kind == Bill.BillKind.SALE and self.movement != self.Movement.REMOVE:
            raise ValidationError("Sale lines must remove stock.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def line_cost_total(self):
        return (self.quantity * self.unit_cp).quantize(Decimal("0.01"))


class VendorPayment(models.Model):
    """Cash/bank payment to a supplier, allocated across one or more purchase bills."""

    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="vendor_payments",
    )
    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="vendor_payments",
    )
    vendor = models.ForeignKey(
        Vendor,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    seq = models.PositiveIntegerField(editable=False, db_index=True)
    payment_code = models.CharField(max_length=32, editable=False, db_index=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_cash = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    paid_bank = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    paid_esewa = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    notes = models.TextField(blank=True)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_vendor_payments",
    )

    class Meta:
        ordering = ["-occurred_at", "-seq"]

    def __str__(self):
        return self.payment_code

    def save(self, *args, **kwargs):
        if self._state.adding:
            self.seq, self.payment_code = self._allocate_payment_code()
        super().save(*args, **kwargs)

    def _allocate_payment_code(self):
        with transaction.atomic():
            seq, _ = RestaurantSequence.objects.select_for_update().get_or_create(
                restaurant=self.restaurant,
                defaults={
                    "next_product_num": 1,
                    "next_bill_seq": 1,
                    "next_vendor_payment_seq": 1,
                },
            )
            n = seq.next_vendor_payment_seq
            seq.next_vendor_payment_seq = n + 1
            seq.save(update_fields=["next_vendor_payment_seq"])
            code = f"VP{self.restaurant_id}-{n:06d}"
            return n, code


class VendorPaymentAllocation(models.Model):
    vendor_payment = models.ForeignKey(
        VendorPayment,
        on_delete=models.CASCADE,
        related_name="allocations",
    )
    bill = models.ForeignKey(
        Bill,
        on_delete=models.PROTECT,
        related_name="vendor_payment_allocations",
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.vendor_payment.payment_code} → {self.bill.bill_code}"


def stock_quantity_for_item(master_item: MasterItem) -> Decimal:
    """Posted or paid bills only."""
    ok_status = [Bill.Status.POSTED, Bill.Status.PAID]
    add = (
        BillLine.objects.filter(
            master_item=master_item,
            movement=BillLine.Movement.ADD,
            bill__status__in=ok_status,
        ).aggregate(s=Sum("quantity"))["s"]
        or Decimal("0")
    )
    rem = (
        BillLine.objects.filter(
            master_item=master_item,
            movement=BillLine.Movement.REMOVE,
            bill__status__in=ok_status,
        ).aggregate(s=Sum("quantity"))["s"]
        or Decimal("0")
    )
    return add - rem

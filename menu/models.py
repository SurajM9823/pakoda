from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from inventory.models import MasterItem
from superadmin.models import Restaurant


class MenuCategory(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="menu_categories",
    )
    name = models.CharField(max_length=120)
    sort_order = models.PositiveSmallIntegerField(default=0)
    image = models.ImageField(
        upload_to="menu/categories/%Y/%m/",
        blank=True,
        null=True,
        help_text="Optional photo for the category (e.g. section header).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "Menu categories"

    def __str__(self):
        return f"{self.restaurant_id} · {self.name}"


class MenuItem(models.Model):
    category = models.ForeignKey(
        MenuCategory,
        on_delete=models.CASCADE,
        related_name="items",
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    portion_label = models.CharField(
        max_length=120,
        blank=True,
        help_text='How it is sold, e.g. "1 pc", "250 g plate", "Half plate".',
    )
    sell_price = models.DecimalField(
        "Selling price (NPR)",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    sort_order = models.PositiveSmallIntegerField(default=0)
    image = models.ImageField(
        upload_to="menu/items/%Y/%m/",
        blank=True,
        null=True,
        help_text="Main photo for this menu line.",
    )
    is_active = models.BooleanField(default=True)
    show_on_public_site = models.BooleanField(
        default=True,
        help_text="If off, hidden from the public menu API.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "sort_order", "name"]

    def __str__(self):
        return f"{self.category.name} · {self.name}"

    @property
    def restaurant(self):
        return self.category.restaurant


class MenuItemIngredient(models.Model):
    """Stock (master item) quantities used for one sellable menu unit — for records / costing."""

    menu_item = models.ForeignKey(
        MenuItem,
        on_delete=models.CASCADE,
        related_name="ingredients",
    )
    master_item = models.ForeignKey(
        MasterItem,
        on_delete=models.PROTECT,
        related_name="menu_ingredient_lines",
    )
    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        help_text="Amount of this stock item for one menu portion (same unit as inventory).",
    )
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["menu_item", "master_item"],
                name="menu_item_ingredient_unique_master",
            ),
        ]

    def __str__(self):
        return f"{self.menu_item.name} ← {self.master_item.name}"

    def clean(self):
        super().clean()
        if self.menu_item_id and self.master_item_id:
            mr = self.menu_item.category.restaurant_id
            if self.master_item.restaurant_id != mr:
                raise ValidationError("Ingredient must belong to the same outlet as the menu item.")

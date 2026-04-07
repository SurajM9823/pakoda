from decimal import Decimal

from rest_framework import serializers

from inventory.models import MasterItem
from inventory.services import money2, unit_pricing_for_master_item

from .models import MenuCategory, MenuItem, MenuItemIngredient


def _abs_image(request, fieldfile):
    if not fieldfile:
        return None
    return request.build_absolute_uri(fieldfile.url)


class MenuCategorySerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = MenuCategory
        fields = [
            "id",
            "name",
            "sort_order",
            "image_url",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_image_url(self, obj):
        return _abs_image(self.context["request"], obj.image) if obj.image else None


class MenuCategoryWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuCategory
        fields = ["name", "sort_order", "is_active"]


class MenuItemIngredientSerializer(serializers.ModelSerializer):
    product_num = serializers.IntegerField(source="master_item.product_num", read_only=True)
    master_item_name = serializers.CharField(source="master_item.name", read_only=True)
    master_unit_type = serializers.CharField(source="master_item.unit_type", read_only=True)
    master_pricing = serializers.SerializerMethodField()

    class Meta:
        model = MenuItemIngredient
        fields = [
            "id",
            "master_item",
            "product_num",
            "master_item_name",
            "master_unit_type",
            "master_pricing",
            "quantity",
            "note",
        ]
        read_only_fields = ["id", "product_num", "master_item_name", "master_unit_type", "master_pricing"]

    def get_master_pricing(self, obj):
        return unit_pricing_for_master_item(obj.master_item)


class MenuItemIngredientWriteSerializer(serializers.Serializer):
    master_item_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal("0.0001"))
    note = serializers.CharField(required=False, allow_blank=True, default="")


class MenuItemSerializer(serializers.ModelSerializer):
    image_url = serializers.SerializerMethodField()
    ingredients = MenuItemIngredientSerializer(many=True, read_only=True)
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = MenuItem
        fields = [
            "id",
            "category",
            "category_name",
            "name",
            "description",
            "portion_label",
            "sell_price",
            "sort_order",
            "image_url",
            "is_active",
            "show_on_public_site",
            "ingredients",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "category_name", "ingredients", "created_at", "updated_at"]

    def get_image_url(self, obj):
        return _abs_image(self.context["request"], obj.image) if obj.image else None

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["sell_price"] = money2(instance.sell_price)
        return data


class MenuItemWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = MenuItem
        fields = [
            "category",
            "name",
            "description",
            "portion_label",
            "sell_price",
            "sort_order",
            "is_active",
            "show_on_public_site",
        ]

    def validate_category(self, cat):
        restaurant = self.context.get("restaurant")
        if restaurant is not None and cat.restaurant_id != restaurant.id:
            raise serializers.ValidationError("Invalid category for this outlet.")
        return cat

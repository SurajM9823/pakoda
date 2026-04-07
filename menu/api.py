from decimal import Decimal

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from inventory.api import _can_edit_master, _require_restaurant
from inventory.models import MasterItem
from inventory.services import money2

from superadmin.models import Restaurant

from .models import MenuCategory, MenuItem, MenuItemIngredient
from .serializers import (
    MenuCategorySerializer,
    MenuCategoryWriteSerializer,
    MenuItemIngredientSerializer,
    MenuItemIngredientWriteSerializer,
    MenuItemSerializer,
    MenuItemWriteSerializer,
)


def _ctx(request, restaurant):
    return {"request": request, "restaurant": restaurant}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def menu_categories_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if request.method == "GET":
        qs = MenuCategory.objects.filter(restaurant=restaurant).order_by("sort_order", "name")
        return Response(MenuCategorySerializer(qs, many=True, context={"request": request}).data)
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    ser = MenuCategoryWriteSerializer(data=request.data, context=_ctx(request, restaurant))
    ser.is_valid(raise_exception=True)
    cat = MenuCategory(restaurant=restaurant, **ser.validated_data)
    cat.save()
    return Response(
        MenuCategorySerializer(cat, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def menu_category_detail_view(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    cat = get_object_or_404(MenuCategory, pk=pk, restaurant=restaurant)
    if request.method == "GET":
        return Response(MenuCategorySerializer(cat, context={"request": request}).data)
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if request.method == "DELETE":
        cat.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = MenuCategoryWriteSerializer(
        cat, data=request.data, partial=True, context=_ctx(request, restaurant)
    )
    ser.is_valid(raise_exception=True)
    ser.save()
    cat.refresh_from_db()
    return Response(MenuCategorySerializer(cat, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def menu_category_image_view(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    cat = get_object_or_404(MenuCategory, pk=pk, restaurant=restaurant)
    f = request.FILES.get("image")
    if not f:
        return Response({"detail": "Missing file field 'image'."}, status=status.HTTP_400_BAD_REQUEST)
    cat.image = f
    cat.save(update_fields=["image", "updated_at"])
    return Response(MenuCategorySerializer(cat, context={"request": request}).data)


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def menu_items_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    qs = (
        MenuItem.objects.filter(category__restaurant=restaurant)
        .select_related("category")
        .prefetch_related("ingredients__master_item")
        .order_by("category", "sort_order", "name")
    )
    cat_id = request.query_params.get("category")
    if cat_id not in (None, ""):
        try:
            qs = qs.filter(category_id=int(cat_id))
        except (ValueError, TypeError):
            pass
    if request.method == "GET":
        return Response(MenuItemSerializer(qs[:500], many=True, context={"request": request}).data)
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    ser = MenuItemWriteSerializer(data=request.data, context={**_ctx(request, restaurant), "request": request})
    ser.is_valid(raise_exception=True)
    item = MenuItem(**ser.validated_data)
    item.save()
    item.refresh_from_db()
    return Response(
        MenuItemSerializer(item, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def menu_item_detail_view(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    item = get_object_or_404(
        MenuItem.objects.select_related("category").prefetch_related("ingredients__master_item"),
        pk=pk,
        category__restaurant=restaurant,
    )
    if request.method == "GET":
        return Response(MenuItemSerializer(item, context={"request": request}).data)
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if request.method == "DELETE":
        item.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = MenuItemWriteSerializer(
        item, data=request.data, partial=True, context={**_ctx(request, restaurant), "request": request}
    )
    ser.is_valid(raise_exception=True)
    ser.save()
    item.refresh_from_db()
    return Response(MenuItemSerializer(item, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser, FormParser])
def menu_item_image_view(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    item = get_object_or_404(MenuItem, pk=pk, category__restaurant=restaurant)
    f = request.FILES.get("image")
    if not f:
        return Response({"detail": "Missing file field 'image'."}, status=status.HTTP_400_BAD_REQUEST)
    item.image = f
    item.save(update_fields=["image", "updated_at"])
    return Response(MenuItemSerializer(item, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def menu_item_ingredients_view(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    item = get_object_or_404(MenuItem, pk=pk, category__restaurant=restaurant)
    w = MenuItemIngredientWriteSerializer(data=request.data)
    w.is_valid(raise_exception=True)
    mid = w.validated_data["master_item_id"]
    master = get_object_or_404(MasterItem, pk=mid, restaurant=restaurant, is_active=True)
    if MenuItemIngredient.objects.filter(menu_item=item, master_item=master).exists():
        return Response(
            {"detail": "That stock item is already linked to this menu line."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    row = MenuItemIngredient(
        menu_item=item,
        master_item=master,
        quantity=w.validated_data["quantity"],
        note=(w.validated_data.get("note") or "")[:255],
    )
    row.full_clean()
    row.save()
    return Response(
        MenuItemIngredientSerializer(row, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def menu_item_ingredient_detail_view(request, pk, ing_pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can change the menu."},
            status=status.HTTP_403_FORBIDDEN,
        )
    item = get_object_or_404(MenuItem, pk=pk, category__restaurant=restaurant)
    ing = get_object_or_404(MenuItemIngredient, pk=ing_pk, menu_item=item)
    if request.method == "DELETE":
        ing.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    qty = request.data.get("quantity")
    note = request.data.get("note")
    if qty is not None:
        try:
            q = Decimal(str(qty)).quantize(Decimal("0.0001"))
            if q <= 0:
                raise ValueError
            ing.quantity = q
        except (ValueError, ArithmeticError):
            return Response({"detail": "Invalid quantity."}, status=status.HTTP_400_BAD_REQUEST)
    if note is not None:
        ing.note = str(note)[:255]
    ing.full_clean()
    ing.save()
    return Response(MenuItemIngredientSerializer(ing, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([AllowAny])
def menu_public_catalog_view(request):
    try:
        rid = int(request.query_params.get("restaurant", "0"))
    except (ValueError, TypeError):
        rid = 0
    if not rid:
        return Response({"categories": [], "detail": "Pass ?restaurant=<outlet_id>"})
    restaurant = get_object_or_404(Restaurant, pk=rid, is_active=True)
    categories = (
        MenuCategory.objects.filter(restaurant=restaurant, is_active=True)
        .order_by("sort_order", "name")
        .prefetch_related("items")
    )
    out_cats = []
    for c in categories:
        items = [it for it in c.items.all() if it.is_active and it.show_on_public_site]
        items.sort(key=lambda x: (x.sort_order, x.name.lower()))
        out_cats.append(
            {
                "id": c.id,
                "name": c.name,
                "sort_order": c.sort_order,
                "image_url": request.build_absolute_uri(c.image.url) if c.image else None,
                "items": [
                    {
                        "id": it.id,
                        "name": it.name,
                        "description": it.description,
                        "portion_label": it.portion_label,
                        "sell_price": money2(it.sell_price),
                        "image_url": request.build_absolute_uri(it.image.url) if it.image else None,
                    }
                    for it in items
                ],
            }
        )
    return Response(
        {
            "restaurant_id": restaurant.id,
            "restaurant_name": restaurant.name,
            "source": "menu_catalog",
            "categories": out_cats,
        }
    )

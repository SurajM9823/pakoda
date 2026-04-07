from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from superadmin.models import Restaurant, RestaurantStaff
from superadmin.utils import current_fiscal_year

from .models import Bill, BillLine, MasterItem, Vendor, VendorPayment, stock_quantity_for_item
from .services import (
    INGREDIENT_USE_REASONS,
    UNIT_PRICING_META,
    bill_balance_due,
    bill_subtotal,
    create_vendor_payment,
    ingredient_use_list_bills,
    money2,
    net_accounts_payable,
    post_ingredient_use,
    post_ingredient_use_batch,
    purchase_cash_out_summary,
    qty2,
    refresh_bill_paid_flags,
    restaurant_money_flow_summary,
    stock_incoming_rows,
    supplier_activity_totals,
    supplier_ledger_rows,
    unit_pricing_for_master_item,
    vendor_money_flow_snapshot,
    vendor_net_open_balance,
)
from .serializers import (
    BillCreateSerializer,
    BillLineCreateSerializer,
    BillLineSerializer,
    BillSerializer,
    BillUpdateSerializer,
    IngredientUseBatchCreateSerializer,
    IngredientUseCreateSerializer,
    MasterItemSerializer,
    MasterItemWriteSerializer,
    VendorPaymentCreateSerializer,
    VendorPaymentSerializer,
    VendorSerializer,
)


def _restaurant_for_request(request):
    user = request.user
    if not user.is_authenticated:
        return None
    if user.is_superuser:
        rid = request.session.get("superadmin_active_restaurant_id")
        if rid is None:
            rid = request.query_params.get("restaurant") or request.headers.get("X-Restaurant-Id")
        if rid is None:
            return None
        try:
            return Restaurant.objects.get(pk=int(rid), is_active=True)
        except (ValueError, TypeError, Restaurant.DoesNotExist):
            return None
    try:
        profile = user.restaurant_profile
    except RestaurantStaff.DoesNotExist:
        return None
    if not profile.is_active or not profile.restaurant.is_active:
        return None
    return profile.restaurant


def _require_restaurant(request):
    r = _restaurant_for_request(request)
    if r is None:
        return None, Response(
            {"detail": "Select an outlet (superadmin scope) or sign in with a restaurant account."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return r, None


def _can_edit_master(user, restaurant) -> bool:
    if user.is_superuser:
        return True
    try:
        p = user.restaurant_profile
    except RestaurantStaff.DoesNotExist:
        return False
    if p.restaurant_id != restaurant.id:
        return False
    return p.role == RestaurantStaff.Role.RESTAURANT_ADMIN and p.is_active


def _portal_staff_ok(user, restaurant) -> bool:
    if user.is_superuser:
        return True
    try:
        p = user.restaurant_profile
    except RestaurantStaff.DoesNotExist:
        return False
    return p.is_active and p.restaurant_id == restaurant.id


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def meta_view(request):
    return Response(
        {
            "unit_types": [{"value": c[0], "label": c[1]} for c in MasterItem.UnitType.choices],
            "unit_pricing_meta": {k: v for k, v in UNIT_PRICING_META.items()},
            "bill_kinds": [{"value": c[0], "label": c[1]} for c in Bill.BillKind.choices],
            "bill_statuses": [{"value": c[0], "label": c[1]} for c in Bill.Status.choices],
            "ingredient_use_reasons": [{"value": c[0], "label": c[1]} for c in INGREDIENT_USE_REASONS],
        }
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def master_item_list_create(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if request.method == "GET":
        q = request.query_params.get("q", "").strip()
        qs = MasterItem.objects.filter(restaurant=restaurant, is_active=True).order_by("product_num")
        if q:
            if q.isdigit():
                qs = qs.filter(Q(product_num=int(q)) | Q(name__icontains=q))
            else:
                qs = qs.filter(name__icontains=q)
        ser = MasterItemSerializer(
            qs[:200], many=True, context={"request": request}
        )
        return Response(ser.data)
    if not _can_edit_master(request.user, restaurant):
        return Response(
            {"detail": "Only restaurant admins can create master items here (use quick-add while receiving)."},
            status=status.HTTP_403_FORBIDDEN,
        )
    ser = MasterItemWriteSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    item = MasterItem(restaurant=restaurant, **ser.validated_data)
    item.save()
    return Response(
        MasterItemSerializer(item, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def master_item_detail(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    item = get_object_or_404(MasterItem, pk=pk, restaurant=restaurant)
    if request.method == "GET":
        return Response(MasterItemSerializer(item, context={"request": request}).data)
    if not _can_edit_master(request.user, restaurant):
        return Response(status=status.HTTP_403_FORBIDDEN)
    ser = MasterItemWriteSerializer(item, data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    item = ser.save()
    return Response(MasterItemSerializer(item, context={"request": request}).data)


@api_view(["POST"])
@parser_classes([MultiPartParser, FormParser])
@permission_classes([IsAuthenticated])
def master_item_image_upload(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if not _can_edit_master(request.user, restaurant):
        return Response(status=status.HTTP_403_FORBIDDEN)
    item = get_object_or_404(MasterItem, pk=pk, restaurant=restaurant)
    f = request.FILES.get("image")
    if not f:
        return Response({"detail": "Missing file field 'image'."}, status=status.HTTP_400_BAD_REQUEST)
    item.image = f
    item.save(update_fields=["image", "updated_at"])
    return Response(MasterItemSerializer(item, context={"request": request}).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stock_summary(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    qs = MasterItem.objects.filter(restaurant=restaurant, is_active=True).order_by("product_num")
    data = []
    for it in qs[:500]:
        img = None
        if it.image:
            img = request.build_absolute_uri(it.image.url)
        data.append(
            {
                "id": it.id,
                "product_num": it.product_num,
                "name": it.name,
                "unit_type": it.unit_type,
                "pieces_per_pack": it.pieces_per_pack,
                "sp_per_piece": it.sp_per_piece,
                "cp": money2(it.cp),
                "sp": money2(it.sp),
                "on_hand": qty2(stock_quantity_for_item(it)),
                "is_sold_as_menu": it.is_sold_as_menu,
                "is_used_as_ingredient": it.is_used_as_ingredient,
                "show_on_public_site": it.show_on_public_site,
                "image_url": img,
                "pricing": unit_pricing_for_master_item(it),
            }
        )
    return Response({"results": data})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def bill_list_create(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if request.method == "GET":
        kind = request.query_params.get("kind")
        kinds = request.query_params.get("kinds")
        limit = int(request.query_params.get("limit", "40"))
        qs = Bill.objects.filter(restaurant=restaurant).prefetch_related("lines__master_item")
        if kinds:
            parts = [p.strip() for p in kinds.split(",") if p.strip()]
            if parts:
                qs = qs.filter(bill_kind__in=parts)
        elif kind:
            qs = qs.filter(bill_kind=kind)
        bills = qs.order_by("-occurred_at", "-seq")[:limit]
        bills = bills.select_related("vendor")
        return Response(BillSerializer(bills, many=True).data)
    ser = BillCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    fy = current_fiscal_year(restaurant)
    vendor = None
    vid = ser.validated_data.get("vendor_id")
    if vid is not None:
        vendor = get_object_or_404(Vendor, pk=vid, restaurant=restaurant, is_active=True)
    bill = Bill(
        restaurant=restaurant,
        fiscal_year=fy,
        bill_kind=ser.validated_data["bill_kind"],
        vendor=vendor,
        supplier_reference=ser.validated_data.get("supplier_reference", ""),
        notes=ser.validated_data.get("notes", ""),
        created_by=request.user if request.user.is_authenticated else None,
    )
    bill.save()
    bill = Bill.objects.select_related("vendor").prefetch_related("lines__master_item").get(pk=bill.pk)
    return Response(BillSerializer(bill).data, status=status.HTTP_201_CREATED)


def _movement_for_kind(kind: str) -> str:
    if kind == Bill.BillKind.PURCHASE:
        return BillLine.Movement.ADD
    if kind == Bill.BillKind.SALE:
        return BillLine.Movement.REMOVE
    if kind == Bill.BillKind.PURCHASE_RETURN:
        return BillLine.Movement.REMOVE
    return BillLine.Movement.ADD


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([IsAuthenticated])
def bill_detail(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    bill = get_object_or_404(
        Bill.objects.select_related("vendor").prefetch_related("lines__master_item"),
        pk=pk,
        restaurant=restaurant,
    )
    if request.method == "GET":
        return Response(BillSerializer(bill).data)
    if request.method == "DELETE":
        if bill.status != Bill.Status.DRAFT:
            return Response({"detail": "Only draft bills can be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        bill.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    ser = BillUpdateSerializer(data=request.data, partial=True)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    new_status = data.get("status", bill.status)
    effective_discount = bill.discount_amount
    if bill.status == Bill.Status.DRAFT and "discount_amount" in data:
        effective_discount = data["discount_amount"]
    wants_paid = data.get("is_paid") is True or new_status == Bill.Status.PAID
    if wants_paid and bill.status == Bill.Status.DRAFT:
        return Response(
            {"detail": "Post the bill first (stock is updated on post), then mark paid."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if new_status == Bill.Status.POSTED and bill.status == Bill.Status.DRAFT:
        bill = Bill.objects.prefetch_related("lines__master_item").select_related("vendor").get(pk=bill.pk)
        if not bill.lines.exists():
            return Response({"detail": "Add at least one line before posting."}, status=status.HTTP_400_BAD_REQUEST)
        sub = bill_subtotal(bill)
        if effective_discount > sub:
            return Response(
                {"detail": "Discount cannot be greater than line subtotal."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if bill.bill_kind in (Bill.BillKind.SALE, Bill.BillKind.PURCHASE_RETURN):
            for line in bill.lines.select_related("master_item"):
                avail = stock_quantity_for_item(line.master_item)
                if avail < line.quantity:
                    return Response(
                        {
                            "detail": f"Not enough stock for #{line.master_item.product_num} {line.master_item.name}. "
                            f"Have {avail}, need {line.quantity}."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
        elif bill.bill_kind == Bill.BillKind.ADJUSTMENT:
            for line in bill.lines.select_related("master_item"):
                if line.movement != BillLine.Movement.REMOVE:
                    continue
                avail = stock_quantity_for_item(line.master_item)
                if avail < line.quantity:
                    return Response(
                        {
                            "detail": f"Not enough stock for #{line.master_item.product_num} {line.master_item.name}. "
                            f"Have {avail}, need {line.quantity}."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
    with transaction.atomic():
        if "vendor_id" in data:
            vid = data["vendor_id"]
            if vid is None:
                bill.vendor = None
            else:
                bill.vendor = get_object_or_404(Vendor, pk=vid, restaurant=restaurant, is_active=True)
        if bill.status == Bill.Status.DRAFT and "discount_amount" in data:
            bill.discount_amount = data["discount_amount"]
        if (
            bill.bill_kind != Bill.BillKind.ADJUSTMENT
            and bill.status in (Bill.Status.DRAFT, Bill.Status.POSTED)
            and any(
                k in data
                for k in ("amount_paid", "paid_cash", "paid_bank", "paid_esewa")
            )
        ):
            if any(k in data for k in ("paid_cash", "paid_bank", "paid_esewa")):
                pc = Decimal(str(data.get("paid_cash", bill.paid_cash or 0))).quantize(Decimal("0.01"))
                pb = Decimal(str(data.get("paid_bank", bill.paid_bank or 0))).quantize(Decimal("0.01"))
                pe = Decimal(str(data.get("paid_esewa", bill.paid_esewa or 0))).quantize(Decimal("0.01"))
                bill.paid_cash = pc
                bill.paid_bank = pb
                bill.paid_esewa = pe
                bill.amount_paid = (pc + pb + pe).quantize(Decimal("0.01"))
            elif "amount_paid" in data:
                ap = Decimal(str(data["amount_paid"])).quantize(Decimal("0.01"))
                bill.amount_paid = ap
                bill.paid_cash = ap
                bill.paid_bank = Decimal("0")
                bill.paid_esewa = Decimal("0")
            refresh_bill_paid_flags(bill)
        if "supplier_reference" in data:
            bill.supplier_reference = data["supplier_reference"]
        if "notes" in data:
            bill.notes = data["notes"]
        if "occurred_at" in data:
            bill.occurred_at = data["occurred_at"]
        if "status" in data:
            bill.status = data["status"]
        if "is_paid" in data:
            bill.is_paid = data["is_paid"]
        if bill.is_paid and bill.status == Bill.Status.POSTED:
            bill.status = Bill.Status.PAID
        bill.save()
    bill.refresh_from_db()
    bill = Bill.objects.select_related("vendor").prefetch_related("lines__master_item").get(pk=bill.pk)
    return Response(BillSerializer(bill).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def bill_line_create(request, pk):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    bill = get_object_or_404(Bill, pk=pk, restaurant=restaurant)
    if bill.status != Bill.Status.DRAFT:
        return Response({"detail": "Bill is not editable."}, status=status.HTTP_400_BAD_REQUEST)
    ser = BillLineCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    item = get_object_or_404(MasterItem, pk=d["master_item_id"], restaurant=restaurant, is_active=True)
    movement = d.get("movement") or _movement_for_kind(bill.bill_kind)
    if bill.bill_kind == Bill.BillKind.PURCHASE:
        movement = BillLine.Movement.ADD
    elif bill.bill_kind == Bill.BillKind.SALE:
        movement = BillLine.Movement.REMOVE
    elif bill.bill_kind == Bill.BillKind.PURCHASE_RETURN:
        movement = BillLine.Movement.REMOVE
    line = BillLine(
        bill=bill,
        master_item=item,
        quantity=d["quantity"],
        unit_cp=d.get("unit_cp") or Decimal("0"),
        unit_sp=d.get("unit_sp") or item.sp,
        movement=movement,
        note=d.get("note", ""),
    )
    line.save()
    return Response(BillLineSerializer(line).data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def bill_line_delete(request, pk, line_id):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    bill = get_object_or_404(Bill, pk=pk, restaurant=restaurant)
    if bill.status != Bill.Status.DRAFT:
        return Response({"detail": "Bill is not editable."}, status=status.HTTP_400_BAD_REQUEST)
    line = get_object_or_404(BillLine, pk=line_id, bill=bill)
    line.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def master_quick_create(request):
    """Staff can create a minimal master row while receiving stock."""
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if not _portal_staff_ok(request.user, restaurant):
        return Response(status=status.HTTP_403_FORBIDDEN)
    name = (request.data.get("name") or "").strip()
    if not name:
        return Response({"detail": "Name is required."}, status=status.HTTP_400_BAD_REQUEST)
    cp = Decimal(str(request.data.get("cp") or "0"))
    unit_type = request.data.get("unit_type") or MasterItem.UnitType.PIECE
    if unit_type not in dict(MasterItem.UnitType.choices):
        unit_type = MasterItem.UnitType.PIECE
    pieces = request.data.get("pieces_per_pack")
    pieces_per_pack = int(pieces) if pieces not in (None, "",) else None
    is_sold = bool(request.data.get("is_sold_as_menu"))
    sp = Decimal("0") if not is_sold else Decimal(str(request.data.get("sp") or "0"))
    show_pub = bool(request.data.get("show_on_public_site", True)) if is_sold else False
    sp_per_piece = bool(request.data.get("sp_per_piece")) and unit_type == MasterItem.UnitType.PACKED
    item = MasterItem(
        restaurant=restaurant,
        name=name,
        cp=cp,
        sp=sp,
        unit_type=unit_type,
        pieces_per_pack=pieces_per_pack,
        sp_per_piece=sp_per_piece,
        notes=(request.data.get("notes") or "")[:500],
        is_sold_as_menu=is_sold,
        is_used_as_ingredient=bool(request.data.get("is_used_as_ingredient", True)),
        show_on_public_site=show_pub,
    )
    item.save()
    return Response(
        MasterItemSerializer(item, context={"request": request}).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def vendor_list_create(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if request.method == "GET":
        qs = Vendor.objects.filter(restaurant=restaurant, is_active=True).order_by("name")
        return Response(VendorSerializer(qs, many=True).data)
    if not _portal_staff_ok(request.user, restaurant):
        return Response(status=status.HTTP_403_FORBIDDEN)
    name = (request.data.get("name") or "").strip()
    if not name:
        return Response({"detail": "Vendor name required."}, status=status.HTTP_400_BAD_REQUEST)
    v = Vendor.objects.create(
        restaurant=restaurant,
        name=name,
        phone=(request.data.get("phone") or "")[:64],
        notes=(request.data.get("notes") or "")[:500],
    )
    return Response(VendorSerializer(v).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def cash_summary_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    try:
        days = int(request.query_params.get("days", "30"))
    except ValueError:
        days = 30
    days = max(1, min(days, 365))
    return Response(purchase_cash_out_summary(restaurant, days=days))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def vendor_open_bills_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    vid = request.query_params.get("vendor_id")
    if not vid:
        return Response({"detail": "vendor_id is required."}, status=status.HTTP_400_BAD_REQUEST)
    vendor = get_object_or_404(Vendor, pk=int(vid), restaurant=restaurant, is_active=True)
    qs = (
        Bill.objects.filter(
            restaurant=restaurant,
            vendor=vendor,
            bill_kind=Bill.BillKind.PURCHASE,
            status=Bill.Status.POSTED,
        )
        .select_related("vendor")
        .prefetch_related("lines__master_item")
        .order_by("occurred_at", "seq")
    )
    out = []
    for b in qs:
        if bill_balance_due(b) > 0:
            out.append(BillSerializer(b).data)
    return Response(out)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def vendor_balances_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    rows = []
    for v in Vendor.objects.filter(restaurant=restaurant, is_active=True).order_by("name"):
        bal = vendor_net_open_balance(restaurant, v)
        rows.append({"id": v.id, "name": v.name, "open_balance": money2(bal)})
    return Response({"results": rows})


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def vendor_payment_list_create(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if request.method == "GET":
        qs = VendorPayment.objects.filter(restaurant=restaurant).select_related("vendor").prefetch_related(
            "allocations__bill"
        )
        vid = request.query_params.get("vendor_id")
        if vid:
            qs = qs.filter(vendor_id=int(vid))
        qs = qs.order_by("-occurred_at", "-seq")[:80]
        return Response(VendorPaymentSerializer(qs, many=True).data)
    if not _portal_staff_ok(request.user, restaurant):
        return Response(status=status.HTTP_403_FORBIDDEN)
    ser = VendorPaymentCreateSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    d = ser.validated_data
    vendor = get_object_or_404(Vendor, pk=d["vendor_id"], restaurant=restaurant, is_active=True)
    fy = current_fiscal_year(restaurant)
    try:
        pay = create_vendor_payment(
            restaurant=restaurant,
            vendor=vendor,
            fiscal_year=fy,
            total_amount=d["total_amount"],
            allocations=d["allocations"],
            notes=d.get("notes") or "",
            occurred_at=d.get("occurred_at"),
            user=request.user,
            paid_cash=d.get("paid_cash"),
            paid_bank=d.get("paid_bank"),
            paid_esewa=d.get("paid_esewa"),
        )
    except ValueError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    pay = VendorPayment.objects.select_related("vendor").prefetch_related("allocations__bill").get(pk=pay.pk)
    return Response(VendorPaymentSerializer(pay).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def return_item_search_view(request):
    """Items available to return: optional filter by posted purchase bill; only in-stock by default."""
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    q = (request.query_params.get("q") or "").strip()
    vendor_id = request.query_params.get("vendor_id")
    bill_ref = (request.query_params.get("purchase_bill") or "").strip()
    in_stock_only = request.query_params.get("in_stock_only", "1") != "0"

    qs = MasterItem.objects.filter(restaurant=restaurant, is_active=True)

    if bill_ref:
        bill = None
        if bill_ref.isdigit():
            bill = Bill.objects.filter(
                restaurant=restaurant, pk=int(bill_ref), bill_kind=Bill.BillKind.PURCHASE
            ).first()
        if bill is None:
            bill = Bill.objects.filter(
                restaurant=restaurant,
                bill_kind=Bill.BillKind.PURCHASE,
                bill_code__icontains=bill_ref,
            ).first()
        if bill is None:
            return Response({"detail": "Purchase bill not found."}, status=status.HTTP_404_NOT_FOUND)
        if vendor_id and bill.vendor_id and int(vendor_id) != bill.vendor_id:
            return Response(
                {"detail": "That bill belongs to a different supplier."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        mid_ids = list(bill.lines.values_list("master_item_id", flat=True).distinct())
        qs = qs.filter(pk__in=mid_ids)

    if q:
        if q.isdigit():
            qs = qs.filter(Q(product_num=int(q)) | Q(name__icontains=q))
        else:
            qs = qs.filter(name__icontains=q)

    out = []
    for it in qs.order_by("product_num")[:100]:
        oh = stock_quantity_for_item(it)
        if in_stock_only and oh <= 0:
            continue
        out.append(MasterItemSerializer(it, context={"request": request}).data)
    return Response(out)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def stock_incoming_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    try:
        limit = int(request.query_params.get("limit", "150"))
    except (ValueError, TypeError):
        limit = 150
    limit = max(1, min(limit, 500))
    days_q = request.query_params.get("days")
    days = None
    if days_q not in (None, ""):
        try:
            days = int(days_q)
        except (ValueError, TypeError):
            days = None
    return Response(stock_incoming_rows(restaurant, limit=limit, days=days))


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def ingredient_uses_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    if request.method == "GET":
        try:
            glimit = int(request.query_params.get("limit", "100"))
        except (ValueError, TypeError):
            glimit = 100
        glimit = max(1, min(glimit, 200))
        return Response({"bills": ingredient_use_list_bills(restaurant, limit=glimit)})
    if not _portal_staff_ok(request.user, restaurant):
        return Response(status=status.HTTP_403_FORBIDDEN)
    data = request.data
    use_batch = isinstance(data.get("lines"), list) and len(data.get("lines")) > 0
    try:
        if use_batch:
            ser = IngredientUseBatchCreateSerializer(data=data)
            ser.is_valid(raise_exception=True)
            d = ser.validated_data
            bill = post_ingredient_use_batch(
                restaurant=restaurant,
                user=request.user,
                lines=d["lines"],
                reason=d["reason"],
                notes=d.get("notes") or "",
            )
        else:
            ser = IngredientUseCreateSerializer(data=data)
            ser.is_valid(raise_exception=True)
            d = ser.validated_data
            bill = post_ingredient_use(
                restaurant=restaurant,
                user=request.user,
                master_item_id=d["master_item_id"],
                quantity=d["quantity"],
                reason=d["reason"],
                notes=d.get("notes") or "",
            )
    except ValueError as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    except MasterItem.DoesNotExist:
        return Response({"detail": "Item not found."}, status=status.HTTP_404_NOT_FOUND)
    bill = Bill.objects.select_related("vendor").prefetch_related("lines__master_item").get(pk=bill.pk)
    return Response(BillSerializer(bill).data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def supplier_ledger_view(request):
    restaurant, err = _require_restaurant(request)
    if err:
        return err
    vendor_id = request.query_params.get("vendor_id")
    fy_id = request.query_params.get("fiscal_year_id")
    rows = supplier_ledger_rows(
        restaurant,
        vendor_id=int(vendor_id) if vendor_id else None,
        fiscal_year_id=int(fy_id) if fy_id else None,
    )
    if vendor_id:
        v = get_object_or_404(Vendor, pk=int(vendor_id), restaurant=restaurant, is_active=True)
        net = vendor_net_open_balance(restaurant, v)
    else:
        net = net_accounts_payable(restaurant)
    owe = max(Decimal("0"), net)
    credit = max(Decimal("0"), -net)
    summary = {
        "net_vendor_position": money2(net),
        "amount_you_owe": money2(owe),
        "vendor_credit_balance": money2(credit),
        "total_you_owe_vendors": money2(owe),
        # Ledger uses signed running total (negative = you owe); empty feed matches -net_accounts_payable.
        "ledger_closing_balance": rows[-1]["balance"] if rows else money2(-net),
    }
    summary.update(supplier_activity_totals(restaurant))
    summary["money_flow"] = restaurant_money_flow_summary(restaurant)
    if vendor_id:
        summary["vendor_money"] = vendor_money_flow_snapshot(restaurant, v)
    return Response({"results": rows, "summary": summary})


@api_view(["GET"])
@permission_classes([AllowAny])
def public_menu_view(request):
    try:
        rid = int(request.query_params.get("restaurant", "0"))
    except (ValueError, TypeError):
        rid = 0
    if not rid:
        return Response({"results": [], "detail": "Pass ?restaurant=<outlet_id>"})
    restaurant = get_object_or_404(Restaurant, pk=rid, is_active=True)
    items = list(
        MasterItem.objects.filter(
            restaurant=restaurant,
            is_active=True,
            is_sold_as_menu=True,
            show_on_public_site=True,
        ).order_by("product_num")[:300]
    )
    return Response(
        {
            "restaurant_id": restaurant.id,
            "restaurant_name": restaurant.name,
            "count": len(items),
            "results": [
                {
                    "id": it.id,
                    "product_num": it.product_num,
                    "name": it.name,
                    "price_npr": money2(it.sp),
                    "price_basis": "per_piece"
                    if it.sp_per_piece
                    else ("per_pack" if it.unit_type == MasterItem.UnitType.PACKED else "per_unit"),
                    "unit_type": it.unit_type,
                    "pieces_per_pack": it.pieces_per_pack,
                    "sp_per_piece": it.sp_per_piece,
                    "image_url": request.build_absolute_uri(it.image.url) if it.image else None,
                }
                for it in items
            ],
        }
    )

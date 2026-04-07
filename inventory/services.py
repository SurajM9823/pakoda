from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Optional, Tuple

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import Bill, BillLine, MasterItem, Vendor, VendorPayment, VendorPaymentAllocation, stock_quantity_for_item


# How CP/SP and quantities relate for each stock unit type (UI + API hints).
UNIT_PRICING_META = {
    MasterItem.UnitType.KG: {
        "stock_unit": "kg",
        "cp_label": "Cost price per kg",
        "sp_label": "Selling price per kg (only if sold to customers)",
        "qty_hint": "Stock & purchases: quantity in kg (e.g. 0.5 = 500 g).",
        "ingredient_hint": "Recipe / menu: amount of this item in kg.",
        "line_cost_hint": "Receipt line total = qty (kg) × unit CP (NPR per kg). Use the same unit as CP.",
    },
    MasterItem.UnitType.LITER: {
        "stock_unit": "L",
        "cp_label": "Cost price per litre",
        "sp_label": "Selling price per litre (only if sold)",
        "qty_hint": "Stock & purchases: quantity in litres (e.g. 0.5 = half litre).",
        "ingredient_hint": "Recipe: amount in litres.",
        "line_cost_hint": "Line total = qty (L) × unit CP (NPR per litre).",
    },
    MasterItem.UnitType.PIECE: {
        "stock_unit": "piece",
        "cp_label": "Cost price per piece",
        "sp_label": "Selling price per piece (only if sold)",
        "qty_hint": "Stock & purchases: number of pieces.",
        "ingredient_hint": "Recipe: number of pieces.",
        "line_cost_hint": "Line total = qty (pieces) × unit CP (NPR per piece).",
    },
    MasterItem.UnitType.PACKED: {
        "stock_unit": "pack",
        "cp_label": "Cost price per pack",
        "sp_label": "Selling price (per pack, or per piece if you enable below)",
        "qty_hint": "Stock & purchases: number of packs. Set “pieces per pack” for cigarettes, etc.",
        "ingredient_hint": "Recipe: packs (or use “piece” unit if you track by stick).",
        "line_cost_hint": "Line total = qty (packs) × unit CP (NPR per pack).",
    },
    MasterItem.UnitType.VEGETABLE: {
        "stock_unit": "kg",
        "cp_label": "Cost price per kg",
        "sp_label": "Selling price per kg (only if sold)",
        "qty_hint": "Quantity in kg for stock and receipts.",
        "ingredient_hint": "Amount in kg for recipes.",
        "line_cost_hint": "Line total = qty (kg) × unit CP.",
    },
    MasterItem.UnitType.INGREDIENT: {
        "stock_unit": "unit",
        "cp_label": "Cost price per stock unit (kg, L, etc. — match unit type you chose)",
        "sp_label": "Selling price (only if this item is sold directly)",
        "qty_hint": "Prefer a specific unit (kg / L / piece) via the unit dropdown above.",
        "ingredient_hint": "Same unit as stock.",
        "line_cost_hint": "Line total = qty × unit CP in the same unit.",
    },
    MasterItem.UnitType.OTHER: {
        "stock_unit": "unit",
        "cp_label": "Cost price per unit of stock",
        "sp_label": "Selling price per unit (only if sold)",
        "qty_hint": "Define one consistent unit for qty and CP.",
        "ingredient_hint": "Quantity in that same unit.",
        "line_cost_hint": "Line total = qty × unit CP.",
    },
}


def unit_pricing_for_master_item(item: MasterItem) -> dict:
    """Labels and hints for CP/SP/qty; respects packed + sp_per_piece."""
    meta = UNIT_PRICING_META.get(item.unit_type) or UNIT_PRICING_META[MasterItem.UnitType.OTHER]
    out = {k: v for k, v in meta.items()}
    if item.unit_type == MasterItem.UnitType.PACKED and item.sp_per_piece:
        out["sp_label"] = "Selling price per piece (CP stays per pack)"
        if item.pieces_per_pack:
            out["line_cost_hint"] = (
                "Receipt: qty in packs × unit CP (per pack). "
                f"SP applies per piece ({item.pieces_per_pack} pcs per pack)."
            )
    return out


def money2(value) -> str:
    if value is None:
        return "0.00"
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.01")))


def qty2(value) -> str:
    if value is None:
        return "0.00"
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return str(d.quantize(Decimal("0.01")))


def bill_subtotal(bill: Bill) -> Decimal:
    total = Decimal("0")
    for ln in bill.lines.all():
        total += ln.line_cost_total
    return total.quantize(Decimal("0.01"))


def bill_net_payable(bill: Bill) -> Decimal:
    sub = bill_subtotal(bill)
    disc = (bill.discount_amount or Decimal("0")).quantize(Decimal("0.01"))
    return (sub - disc).quantize(Decimal("0.01"))


def bill_balance_due(bill: Bill) -> Decimal:
    net = bill_net_payable(bill)
    paid = (bill.amount_paid or Decimal("0")).quantize(Decimal("0.01"))
    return (net - paid).quantize(Decimal("0.01"))


def vendor_net_open_balance(restaurant, vendor: Vendor) -> Decimal:
    """Positive = you owe the vendor (after purchase returns as credits)."""
    posted_purchases = Bill.objects.filter(
        restaurant=restaurant,
        vendor=vendor,
        bill_kind=Bill.BillKind.PURCHASE,
        status=Bill.Status.POSTED,
    )
    total = Decimal("0")
    for b in posted_purchases:
        total += bill_balance_due(b)
    posted_returns = Bill.objects.filter(
        restaurant=restaurant,
        vendor=vendor,
        bill_kind=Bill.BillKind.PURCHASE_RETURN,
        status=Bill.Status.POSTED,
    )
    credits = Decimal("0")
    for b in posted_returns:
        credits += bill_net_payable(b)
    return (total - credits).quantize(Decimal("0.01"))


def net_accounts_payable(restaurant) -> Decimal:
    """Signed net: posted purchase balance due minus posted return credits (all vendors + no-vendor bills)."""
    due = Decimal("0")
    for b in Bill.objects.filter(
        restaurant=restaurant,
        bill_kind=Bill.BillKind.PURCHASE,
        status=Bill.Status.POSTED,
    ):
        due += bill_balance_due(b)
    credits = Decimal("0")
    for b in Bill.objects.filter(
        restaurant=restaurant,
        bill_kind=Bill.BillKind.PURCHASE_RETURN,
        status=Bill.Status.POSTED,
    ):
        credits += bill_net_payable(b)
    return (due - credits).quantize(Decimal("0.01"))


def total_vendor_ap_outstanding(restaurant) -> Decimal:
    """Gross amount owed (never negative); use net_accounts_payable for signed position."""
    n = net_accounts_payable(restaurant)
    return max(Decimal("0"), n).quantize(Decimal("0.01"))


def refresh_bill_paid_flags(bill: Bill) -> None:
    due = bill_balance_due(bill)
    if bill.status == Bill.Status.POSTED and due <= 0:
        bill.status = Bill.Status.PAID
        bill.is_paid = True
    elif bill.status == Bill.Status.PAID and due > 0:
        bill.status = Bill.Status.POSTED
        bill.is_paid = False


@transaction.atomic
def create_vendor_payment(
    *,
    restaurant,
    vendor: Vendor,
    fiscal_year,
    total_amount: Decimal,
    allocations: list,
    notes: str,
    occurred_at,
    user,
    paid_cash: Optional[Decimal] = None,
    paid_bank: Optional[Decimal] = None,
    paid_esewa: Optional[Decimal] = None,
) -> VendorPayment:
    total_amount = total_amount.quantize(Decimal("0.01"))
    alloc_sum = Decimal("0")
    for row in allocations:
        alloc_sum += Decimal(str(row["amount"])).quantize(Decimal("0.01"))
    if alloc_sum != total_amount:
        raise ValueError("Allocation amounts must sum to the payment total.")
    if paid_cash is None and paid_bank is None and paid_esewa is None:
        pc = total_amount
        pb = pe = Decimal("0")
    else:
        pc = (paid_cash if paid_cash is not None else Decimal("0")).quantize(Decimal("0.01"))
        pb = (paid_bank if paid_bank is not None else Decimal("0")).quantize(Decimal("0.01"))
        pe = (paid_esewa if paid_esewa is not None else Decimal("0")).quantize(Decimal("0.01"))
    if (pc + pb + pe).quantize(Decimal("0.01")) != total_amount:
        raise ValueError("Cash / bank / eSewa amounts must sum to the payment total.")
    pay = VendorPayment(
        restaurant=restaurant,
        fiscal_year=fiscal_year,
        vendor=vendor,
        total_amount=total_amount,
        paid_cash=pc,
        paid_bank=pb,
        paid_esewa=pe,
        notes=notes or "",
        occurred_at=occurred_at or timezone.now(),
        created_by=user if user and user.is_authenticated else None,
    )
    pay.save()
    for row in allocations:
        amt = Decimal(str(row["amount"])).quantize(Decimal("0.01"))
        if amt <= 0:
            raise ValueError("Each allocation must be positive.")
        try:
            bill = Bill.objects.select_for_update().get(pk=int(row["bill_id"]), restaurant=restaurant)
        except Bill.DoesNotExist as e:
            raise ValueError("Bill not found for allocation.") from e
        if bill.vendor_id != vendor.id:
            raise ValueError(f"Bill {bill.bill_code} is not for this vendor.")
        if bill.bill_kind != Bill.BillKind.PURCHASE:
            raise ValueError("Only purchase bills can receive payment allocations.")
        if bill.status not in (Bill.Status.POSTED, Bill.Status.PAID):
            raise ValueError(f"Bill {bill.bill_code} is not open for payment.")
        due = bill_balance_due(bill)
        if amt > due:
            raise ValueError(
                f"Bill {bill.bill_code}: allocation {money2(amt)} exceeds balance due {money2(due)}."
            )
        bill.amount_paid = (bill.amount_paid or Decimal("0")) + amt
        refresh_bill_paid_flags(bill)
        bill.save(update_fields=["amount_paid", "status", "is_paid", "updated_at"])
        VendorPaymentAllocation.objects.create(vendor_payment=pay, bill=bill, amount=amt)
    return pay


def supplier_ledger_rows(restaurant, vendor_id=None, fiscal_year_id=None):
    """Chronological debit/credit rows.

    Debit = obligation from purchase (you owe more). Credit = pay on receipt, VP, or return (you owe less).
    Running balance starts at 0 and uses cash-style sign: negative = you owe the vendor; positive = vendor credit.
    """
    rows = []
    bill_q = Bill.objects.filter(restaurant=restaurant).select_related("vendor")
    if vendor_id:
        bill_q = bill_q.filter(vendor_id=int(vendor_id))
    if fiscal_year_id:
        bill_q = bill_q.filter(fiscal_year_id=int(fiscal_year_id))
    purchase_bills = bill_q.filter(
        bill_kind=Bill.BillKind.PURCHASE,
        status__in=[Bill.Status.POSTED, Bill.Status.PAID],
    ).order_by("occurred_at", "seq", "id")
    alloc_by_bill = {}
    alloc_q = VendorPaymentAllocation.objects.filter(bill__restaurant=restaurant).values("bill_id").annotate(
        s=Sum("amount")
    )
    for row in alloc_q:
        alloc_by_bill[row["bill_id"]] = row["s"] or Decimal("0")

    for b in purchase_bills:
        net = bill_net_payable(b)
        if net <= 0:
            continue
        rows.append(
            {
                "occurred_at": b.occurred_at.isoformat(),
                "sort_key": (b.occurred_at.isoformat(), 0, b.bill_code),
                "kind": "purchase",
                "reference": b.display_reference,
                "bill_id": b.id,
                "vendor_id": b.vendor_id,
                "vendor_name": b.vendor.name if b.vendor_id else "",
                "debit": money2(net),
                "credit": "0.00",
                "note": (b.supplier_reference or "")[:120],
            }
        )
        paid = (b.amount_paid or Decimal("0")).quantize(Decimal("0.01"))
        via_vp = (alloc_by_bill.get(b.id) or Decimal("0")).quantize(Decimal("0.01"))
        direct = (paid - via_vp).quantize(Decimal("0.01"))
        if direct > 0:
            split = payment_split_note(b)
            recv_note = "Paid on receive " + money2(direct)
            if split:
                recv_note += " (bill split: " + split + ")"
            rows.append(
                {
                    "occurred_at": b.occurred_at.isoformat(),
                    "sort_key": (b.occurred_at.isoformat(), 1, b.bill_code + "-p"),
                    "kind": "receipt_payment",
                    "reference": b.display_reference,
                    "bill_id": b.id,
                    "vendor_id": b.vendor_id,
                    "vendor_name": b.vendor.name if b.vendor_id else "",
                    "debit": "0.00",
                    "credit": money2(direct),
                    "note": recv_note[:220],
                }
            )

    for b in bill_q.filter(
        bill_kind=Bill.BillKind.PURCHASE_RETURN,
        status__in=[Bill.Status.POSTED, Bill.Status.PAID],
    ).order_by("occurred_at", "seq", "id"):
        net = bill_net_payable(b)
        if net <= 0:
            continue
        rnote = "Return to supplier"
        rsplit = payment_split_note(b)
        if rsplit:
            rnote += " · refund received: " + rsplit
        rows.append(
            {
                "occurred_at": b.occurred_at.isoformat(),
                "sort_key": (b.occurred_at.isoformat(), 0, b.bill_code),
                "kind": "return",
                "reference": b.bill_code,
                "bill_id": b.id,
                "vendor_id": b.vendor_id,
                "vendor_name": b.vendor.name if b.vendor_id else "",
                "debit": "0.00",
                "credit": money2(net),
                "note": rnote[:220],
            }
        )

    pay_q = VendorPayment.objects.filter(restaurant=restaurant).select_related("vendor").prefetch_related(
        "allocations__bill"
    )
    if vendor_id:
        pay_q = pay_q.filter(vendor_id=int(vendor_id))
    if fiscal_year_id:
        pay_q = pay_q.filter(fiscal_year_id=int(fiscal_year_id))
    for p in pay_q.order_by("occurred_at", "seq", "id"):
        alloc_refs = ", ".join(a.bill.display_reference for a in p.allocations.all()[:12])
        note = alloc_refs or p.notes or ""
        vsplit = vendor_payment_split_note(p)
        if vsplit:
            note = (note + " · " + vsplit).strip(" ·") if note else vsplit
        rows.append(
            {
                "occurred_at": p.occurred_at.isoformat(),
                "sort_key": (p.occurred_at.isoformat(), 2, p.payment_code),
                "kind": "vendor_payment",
                "reference": p.payment_code,
                "bill_id": None,
                "vendor_id": p.vendor_id,
                "vendor_name": p.vendor.name,
                "debit": "0.00",
                "credit": money2(p.total_amount),
                "note": note[:220],
            }
        )

    rows.sort(key=lambda r: r["sort_key"])
    bal = Decimal("0")
    out = []
    for r in rows:
        d = Decimal(r["debit"])
        c = Decimal(r["credit"])
        bal = (bal - d + c).quantize(Decimal("0.01"))
        row = {k: v for k, v in r.items() if k != "sort_key"}
        row["balance"] = money2(bal)
        out.append(row)
    return out


def payment_split_note(bill: Bill) -> str:
    parts = []
    pc = bill.paid_cash or Decimal("0")
    pb = bill.paid_bank or Decimal("0")
    pe = bill.paid_esewa or Decimal("0")
    if pc > 0:
        parts.append(f"cash {money2(pc)}")
    if pb > 0:
        parts.append(f"bank {money2(pb)}")
    if pe > 0:
        parts.append(f"eSewa {money2(pe)}")
    return " · ".join(parts) if parts else ""


def vendor_payment_split_note(pay: VendorPayment) -> str:
    parts = []
    pc = pay.paid_cash or Decimal("0")
    pb = pay.paid_bank or Decimal("0")
    pe = pay.paid_esewa or Decimal("0")
    if pc > 0:
        parts.append(f"cash {money2(pc)}")
    if pb > 0:
        parts.append(f"bank {money2(pb)}")
    if pe > 0:
        parts.append(f"eSewa {money2(pe)}")
    return " · ".join(parts) if parts else ""


def payment_wallet_running(restaurant) -> dict:
    """Signed balances from a zero start: negative = net money out, positive = net in (e.g. refunds)."""
    cash = bank = esewa = Decimal("0")
    ok = [Bill.Status.POSTED, Bill.Status.PAID]
    for b in Bill.objects.filter(restaurant=restaurant, bill_kind=Bill.BillKind.PURCHASE, status__in=ok):
        cash -= (b.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        bank -= (b.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        esewa -= (b.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))
    for b in Bill.objects.filter(restaurant=restaurant, bill_kind=Bill.BillKind.PURCHASE_RETURN, status__in=ok):
        cash += (b.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        bank += (b.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        esewa += (b.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))
    for p in VendorPayment.objects.filter(restaurant=restaurant):
        cash -= (p.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        bank -= (p.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        esewa -= (p.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))
    total = (cash + bank + esewa).quantize(Decimal("0.01"))
    return {
        "wallet_cash": money2(cash),
        "wallet_bank": money2(bank),
        "wallet_esewa": money2(esewa),
        "wallet_total": money2(total),
    }


def supplier_activity_totals(restaurant) -> dict:
    """All-time posted/paid purchase stats + open AP."""
    ok = [Bill.Status.POSTED, Bill.Status.PAID]
    purchase_qs = Bill.objects.filter(
        restaurant=restaurant,
        bill_kind=Bill.BillKind.PURCHASE,
        status__in=ok,
    ).prefetch_related("lines")
    total_purchase_net = Decimal("0")
    total_paid_on_bills = Decimal("0")
    for b in purchase_qs:
        total_purchase_net += bill_net_payable(b)
        total_paid_on_bills += (b.amount_paid or Decimal("0")).quantize(Decimal("0.01"))
    alloc_by_bill = {}
    for row in VendorPaymentAllocation.objects.filter(bill__restaurant=restaurant).values("bill_id").annotate(
        s=Sum("amount")
    ):
        alloc_by_bill[row["bill_id"]] = row["s"] or Decimal("0")
    total_paid_at_receive = Decimal("0")
    for b in purchase_qs:
        paid = (b.amount_paid or Decimal("0")).quantize(Decimal("0.01"))
        via_vp = (alloc_by_bill.get(b.id) or Decimal("0")).quantize(Decimal("0.01"))
        total_paid_at_receive += (paid - via_vp).quantize(Decimal("0.01"))
    vp_total = Decimal("0")
    for row in VendorPayment.objects.filter(restaurant=restaurant).values_list("total_amount", flat=True):
        vp_total += (row or Decimal("0")).quantize(Decimal("0.01"))
    net_ap = net_accounts_payable(restaurant)
    owe = max(Decimal("0"), net_ap)
    return {
        "total_purchase_net": money2(total_purchase_net),
        "total_paid_on_receipts": money2(total_paid_at_receive),
        "total_vendor_payments": money2(vp_total),
        "total_recorded_on_bills": money2(total_paid_on_bills),
        "credit_to_pay": money2(owe),
    }


def restaurant_money_flow_summary(restaurant) -> dict:
    """Plain-language money in/out (all vendors), all-time posted/paid."""
    ok = [Bill.Status.POSTED, Bill.Status.PAID]
    purchase_qs = Bill.objects.filter(
        restaurant=restaurant,
        bill_kind=Bill.BillKind.PURCHASE,
        status__in=ok,
    ).prefetch_related("lines")
    total_purchase_net = Decimal("0")
    pur_c = pur_b = pur_e = Decimal("0")
    for b in purchase_qs:
        total_purchase_net += bill_net_payable(b)
        pur_c += (b.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        pur_b += (b.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        pur_e += (b.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))

    vp_c = vp_b = vp_e = Decimal("0")
    vp_total = Decimal("0")
    for p in VendorPayment.objects.filter(restaurant=restaurant):
        vp_c += (p.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        vp_b += (p.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        vp_e += (p.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))
        vp_total += (p.total_amount or Decimal("0")).quantize(Decimal("0.01"))

    ret_c = ret_b = ret_e = Decimal("0")
    return_net = Decimal("0")
    for b in Bill.objects.filter(
        restaurant=restaurant,
        bill_kind=Bill.BillKind.PURCHASE_RETURN,
        status__in=ok,
    ).prefetch_related("lines"):
        return_net += bill_net_payable(b)
        ret_c += (b.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        ret_b += (b.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        ret_e += (b.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))

    net_ap = net_accounts_payable(restaurant)
    owe = max(Decimal("0"), net_ap)
    prepay = max(Decimal("0"), -net_ap)
    wallets = payment_wallet_running(restaurant)

    out_c = (pur_c + vp_c).quantize(Decimal("0.01"))
    out_b = (pur_b + vp_b).quantize(Decimal("0.01"))
    out_e = (pur_e + vp_e).quantize(Decimal("0.01"))

    return {
        "total_purchase_net": money2(total_purchase_net),
        "still_owe_suppliers": money2(owe),
        "supplier_prepaid_credit": money2(prepay),
        "paid_on_receipt_cash": money2(pur_c),
        "paid_on_receipt_bank": money2(pur_b),
        "paid_on_receipt_esewa": money2(pur_e),
        "vp_total": money2(vp_total),
        "vp_cash": money2(vp_c),
        "vp_bank": money2(vp_b),
        "vp_esewa": money2(vp_e),
        "return_credit_goods_value": money2(return_net),
        "return_refund_received_cash": money2(ret_c),
        "return_refund_received_bank": money2(ret_b),
        "return_refund_received_esewa": money2(ret_e),
        "total_paid_out_cash": money2(out_c),
        "total_paid_out_bank": money2(out_b),
        "total_paid_out_esewa": money2(out_e),
        "total_received_back_cash": money2(ret_c),
        "total_received_back_bank": money2(ret_b),
        "total_received_back_esewa": money2(ret_e),
        "net_cash_after_moves": wallets["wallet_cash"],
        "net_bank_after_moves": wallets["wallet_bank"],
        "net_esewa_after_moves": wallets["wallet_esewa"],
        "net_all_channels_after_moves": wallets["wallet_total"],
    }


def vendor_money_flow_snapshot(restaurant, vendor: Vendor) -> dict:
    """Per-vendor purchase / pay / return / still owe (posted & paid bills)."""
    ok = [Bill.Status.POSTED, Bill.Status.PAID]
    purchases = Bill.objects.filter(
        restaurant=restaurant,
        vendor=vendor,
        bill_kind=Bill.BillKind.PURCHASE,
        status__in=ok,
    ).prefetch_related("lines")
    total_purchase_net = Decimal("0")
    pur_c = pur_b = pur_e = Decimal("0")
    applied_on_bills = Decimal("0")
    for b in purchases:
        total_purchase_net += bill_net_payable(b)
        pur_c += (b.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        pur_b += (b.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        pur_e += (b.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))
        applied_on_bills += (b.amount_paid or Decimal("0")).quantize(Decimal("0.01"))

    vp_c = vp_b = vp_e = Decimal("0")
    vp_total = Decimal("0")
    for p in VendorPayment.objects.filter(restaurant=restaurant, vendor=vendor):
        vp_c += (p.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        vp_b += (p.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        vp_e += (p.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))
        vp_total += (p.total_amount or Decimal("0")).quantize(Decimal("0.01"))

    ret_c = ret_b = ret_e = Decimal("0")
    return_goods = Decimal("0")
    for b in Bill.objects.filter(
        restaurant=restaurant,
        vendor=vendor,
        bill_kind=Bill.BillKind.PURCHASE_RETURN,
        status__in=ok,
    ).prefetch_related("lines"):
        return_goods += bill_net_payable(b)
        ret_c += (b.paid_cash or Decimal("0")).quantize(Decimal("0.01"))
        ret_b += (b.paid_bank or Decimal("0")).quantize(Decimal("0.01"))
        ret_e += (b.paid_esewa or Decimal("0")).quantize(Decimal("0.01"))

    net_open = vendor_net_open_balance(restaurant, vendor)
    owe = max(Decimal("0"), net_open)
    prepay = max(Decimal("0"), -net_open)

    return {
        "vendor_name": vendor.name,
        "total_purchase_net": money2(total_purchase_net),
        "amount_applied_on_bills": money2(applied_on_bills),
        "paid_on_receipt_cash": money2(pur_c),
        "paid_on_receipt_bank": money2(pur_b),
        "paid_on_receipt_esewa": money2(pur_e),
        "vp_total": money2(vp_total),
        "vp_cash": money2(vp_c),
        "vp_bank": money2(vp_b),
        "vp_esewa": money2(vp_e),
        "return_credit_goods_value": money2(return_goods),
        "return_refund_received_cash": money2(ret_c),
        "return_refund_received_bank": money2(ret_b),
        "return_refund_received_esewa": money2(ret_e),
        "total_paid_out_cash": money2((pur_c + vp_c).quantize(Decimal("0.01"))),
        "total_paid_out_bank": money2((pur_b + vp_b).quantize(Decimal("0.01"))),
        "total_paid_out_esewa": money2((pur_e + vp_e).quantize(Decimal("0.01"))),
        "still_owe_this_vendor": money2(owe),
        "prepaid_with_this_vendor": money2(prepay),
    }


def purchase_cash_out_summary(restaurant, days: int = 30) -> dict:
    since = timezone.now() - timedelta(days=days)
    base = Bill.objects.filter(
        restaurant=restaurant,
        bill_kind=Bill.BillKind.PURCHASE,
        occurred_at__gte=since,
    )
    paid_qs = base.filter(status__in=[Bill.Status.POSTED, Bill.Status.PAID])
    total_paid = paid_qs.aggregate(s=Sum("amount_paid"))["s"] or Decimal("0")

    net_ap = net_accounts_payable(restaurant)
    outstanding = max(Decimal("0"), net_ap)
    wallets = payment_wallet_running(restaurant)

    return {
        "days": days,
        "purchase_cash_paid": money2(total_paid),
        "vendor_balance_you_owe": money2(outstanding),
        "net_vendor_position": money2(net_ap),
        "current_balance": wallets["wallet_total"],
        "credit_to_pay": money2(outstanding),
        "wallet_cash": wallets["wallet_cash"],
        "wallet_bank": wallets["wallet_bank"],
        "wallet_esewa": wallets["wallet_esewa"],
    }


INGREDIENT_USE_MARKER = "[ingredient_use]"

INGREDIENT_USE_REASONS = [
    ("kitchen_use", "Kitchen / cooking use"),
    ("business_expense", "Ingredient / business expense"),
    ("giveaway", "Giveaway / promo (multi-item)"),
    ("spoilage", "Spoilage / waste"),
    ("staff_meal", "Staff meal"),
    ("gift_friend", "Gift / offer to friend"),
    ("sample", "Sample / tasting"),
    ("theft_loss", "Theft / unaccounted loss"),
    ("other", "Other"),
]


def ingredient_use_reason_allowed(code: str) -> bool:
    return code in {c[0] for c in INGREDIENT_USE_REASONS}


def stock_incoming_rows(restaurant, *, limit: int = 150, days: Optional[int] = None) -> dict:
    """Posted purchase ADD lines: `rows` = one dict per line (true transactions); `by_item` = period roll-up + current on-hand."""
    qs = (
        BillLine.objects.filter(
            bill__restaurant=restaurant,
            bill__bill_kind=Bill.BillKind.PURCHASE,
            bill__status__in=[Bill.Status.POSTED, Bill.Status.PAID],
            movement=BillLine.Movement.ADD,
        )
        .select_related("bill", "master_item", "bill__vendor")
        .order_by("-bill__occurred_at", "-bill__id", "-id")
    )
    if days is not None:
        since = timezone.now() - timedelta(days=int(days))
        qs = qs.filter(bill__occurred_at__gte=since)
    low = Decimal("5")
    rows = []
    for ln in qs[: max(1, min(limit, 500))]:
        item = ln.master_item
        note = (ln.note or "").strip()
        rows.append(
            {
                "line_id": ln.id,
                "bill_id": ln.bill_id,
                "occurred_at": ln.bill.occurred_at.isoformat(),
                "bill_code": ln.bill.bill_code,
                "display_reference": ln.bill.display_reference,
                "vendor_name": ln.bill.vendor.name if ln.bill.vendor_id else "—",
                "master_item_id": item.id,
                "product_num": item.product_num,
                "item_name": item.name,
                "quantity_in": qty2(ln.quantity),
                "unit_cp": money2(ln.unit_cp),
                "line_value": money2(ln.line_cost_total),
                "line_note": note,
            }
        )
    agg: dict = {}
    for ln in qs[:500]:
        mid = ln.master_item_id
        if mid not in agg:
            agg[mid] = {"qty_in": Decimal("0"), "lines": 0, "item": ln.master_item}
        agg[mid]["qty_in"] += ln.quantity
        agg[mid]["lines"] += 1
    by_item = []
    for mid, d in agg.items():
        item = d["item"]
        oh = stock_quantity_for_item(item)
        if oh <= 0:
            alert = "out"
        elif oh < low:
            alert = "low"
        else:
            alert = "ok"
        by_item.append(
            {
                "master_item_id": mid,
                "product_num": item.product_num,
                "item_name": item.name,
                "total_qty_received": qty2(d["qty_in"]),
                "receipt_lines": d["lines"],
                "stock_on_hand_now": qty2(oh),
                "alert": alert,
            }
        )
    _alert_pri = {"out": 0, "low": 1, "ok": 2}
    by_item.sort(
        key=lambda x: (
            _alert_pri.get(x["alert"], 9),
            (x["item_name"] or "").lower(),
        )
    )
    return {"rows": rows, "by_item": by_item}


def _ingredient_reason_label(code: str) -> str:
    for c, lab in INGREDIENT_USE_REASONS:
        if c == code:
            return lab
    return code


def _parse_ingredient_use_bill_notes(bill: Bill) -> Tuple[str, str]:
    tail = (bill.notes or "")[len(INGREDIENT_USE_MARKER) :].strip()
    reason = tail
    extra = ""
    if " | " in tail:
        reason, extra = tail.split(" | ", 1)
    return reason.strip(), extra.strip()


def ingredient_use_list_bills(restaurant, *, limit: int = 100) -> list:
    """One entry per adjustment bill (e.g. one giveaway with many lines)."""
    limit = max(1, min(int(limit), 200))
    qs = (
        Bill.objects.filter(
            restaurant=restaurant,
            bill_kind=Bill.BillKind.ADJUSTMENT,
            status__in=[Bill.Status.POSTED, Bill.Status.PAID],
            notes__startswith=INGREDIENT_USE_MARKER,
        )
        .prefetch_related("lines__master_item")
        .order_by("-occurred_at", "-id")[:limit]
    )
    out = []
    for b in qs:
        reason_code, extra = _parse_ingredient_use_bill_notes(b)
        line_rows = []
        for ln in b.lines.all():
            if ln.movement != BillLine.Movement.REMOVE:
                continue
            line_rows.append(
                {
                    "line_id": ln.id,
                    "product_num": ln.master_item.product_num,
                    "item_name": ln.master_item.name,
                    "quantity": qty2(ln.quantity),
                    "line_note": (ln.note or "").strip(),
                }
            )
        out.append(
            {
                "bill_id": b.id,
                "occurred_at": b.occurred_at.isoformat(),
                "bill_code": b.bill_code,
                "reason": reason_code,
                "reason_label": _ingredient_reason_label(reason_code),
                "notes": extra,
                "lines": line_rows,
            }
        )
    return out


@transaction.atomic
def post_ingredient_use_batch(
    *,
    restaurant,
    user,
    lines: list,
    reason: str,
    notes: str,
) -> Bill:
    if not lines:
        raise ValueError("Add at least one line.")
    if len(lines) > 50:
        raise ValueError("Too many lines (max 50 per bill).")
    if not ingredient_use_reason_allowed(reason):
        raise ValueError("Invalid reason.")

    normalized = []
    for raw in lines:
        mid = int(raw["master_item_id"])
        qty = Decimal(str(raw["quantity"])).quantize(Decimal("0.0001"))
        if qty <= 0:
            raise ValueError("Quantity must be positive.")
        ln_note = (raw.get("note") or "").strip()[:255]
        normalized.append((mid, qty, ln_note))

    qty_by_mid: dict = defaultdict(lambda: Decimal("0"))
    for mid, qty, _ in normalized:
        qty_by_mid[mid] += qty

    for mid in sorted(qty_by_mid.keys()):
        item = MasterItem.objects.select_for_update().get(
            pk=mid, restaurant=restaurant, is_active=True
        )
        avail = stock_quantity_for_item(item)
        need = qty_by_mid[mid]
        if avail < need:
            raise ValueError(
                f"Not enough stock for #{item.product_num} {item.name}: have {qty2(avail)}, need {qty2(need)}."
            )

    from superadmin.utils import current_fiscal_year

    fy = current_fiscal_year(restaurant)
    note_text = (notes or "").strip()[:400]
    bill_notes = f"{INGREDIENT_USE_MARKER} {reason} | {note_text}".strip()[:500]
    bill = Bill(
        restaurant=restaurant,
        fiscal_year=fy,
        bill_kind=Bill.BillKind.ADJUSTMENT,
        status=Bill.Status.DRAFT,
        vendor=None,
        notes=bill_notes,
        created_by=user if user and user.is_authenticated else None,
    )
    bill.save()

    for mid, qty, ln_note in normalized:
        if ln_note:
            line_note = ln_note[:255]
        elif note_text:
            line_note = f"{reason}: {note_text}"[:255]
        else:
            line_note = reason[:255]
        ln = BillLine(
            bill=bill,
            master_item_id=mid,
            quantity=qty,
            unit_cp=Decimal("0"),
            unit_sp=Decimal("0"),
            movement=BillLine.Movement.REMOVE,
            note=line_note,
        )
        ln.save()

    bill.status = Bill.Status.POSTED
    bill.save(update_fields=["status", "updated_at"])
    refresh_bill_paid_flags(bill)
    bill.save(update_fields=["status", "is_paid", "updated_at"])
    return bill


def post_ingredient_use(
    *,
    restaurant,
    user,
    master_item_id: int,
    quantity,
    reason: str,
    notes: str,
) -> Bill:
    return post_ingredient_use_batch(
        restaurant=restaurant,
        user=user,
        lines=[{"master_item_id": int(master_item_id), "quantity": quantity, "note": ""}],
        reason=reason,
        notes=notes or "",
    )

from __future__ import annotations

from typing import TypeVar

from django.db import models
from django.http import HttpRequest
from django.utils import timezone

from .models import FiscalYear, Restaurant, RestaurantStaff

T = TypeVar("T", bound=models.Model)


def get_staff_restaurant(user) -> Restaurant | None:
    if not user.is_authenticated or user.is_superuser:
        return None
    try:
        profile = user.restaurant_profile
    except RestaurantStaff.DoesNotExist:
        return None
    if profile.is_active:
        return profile.restaurant
    return None


def restaurant_for_request(request: HttpRequest) -> Restaurant | None:
    if not request.user.is_authenticated:
        return None
    if request.user.is_superuser:
        rid = request.session.get("superadmin_active_restaurant_id")
        if rid:
            return Restaurant.objects.filter(pk=rid, is_active=True).first()
        return None
    return get_staff_restaurant(request.user)


def queryset_for_restaurant(
    qs: models.QuerySet[T],
    *,
    request: HttpRequest,
    restaurant_field: str = "restaurant",
) -> models.QuerySet[T]:
    if not request.user.is_authenticated:
        return qs.none()
    if request.user.is_superuser:
        r = restaurant_for_request(request)
        if r is not None:
            return qs.filter(**{restaurant_field: r})
        return qs
    staff_restaurant = get_staff_restaurant(request.user)
    if staff_restaurant is None:
        return qs.none()
    return qs.filter(**{restaurant_field: staff_restaurant})


def current_fiscal_year(restaurant: Restaurant) -> FiscalYear | None:
    d = timezone.localdate()
    return (
        FiscalYear.objects.filter(
            restaurant=restaurant,
            is_active=True,
            start_date__lte=d,
            end_date__gte=d,
        )
        .order_by("-start_date")
        .first()
    )

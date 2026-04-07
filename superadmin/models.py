from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


def default_fiscal_year_start():
    y = timezone.localdate().year
    return date(y, 1, 1)


def default_fiscal_year_end():
    y = timezone.localdate().year
    return date(y, 12, 31)


class Restaurant(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, db_index=True)
    is_active = models.BooleanField(default=True)
    phone = models.CharField(max_length=32, blank=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name) or "restaurant"
            slug = base
            n = 2
            while Restaurant.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


class FiscalYear(models.Model):
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="fiscal_years",
    )
    label = models.CharField(
        max_length=64,
        help_text="Display name, e.g. 2026 or FY 2082/83",
    )
    start_date = models.DateField(default=default_fiscal_year_start)
    end_date = models.DateField(default=default_fiscal_year_end)
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive years are hidden from default picks.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-start_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["restaurant", "label"],
                name="superadmin_fiscalyear_unique_label_per_restaurant",
            ),
        ]

    def __str__(self):
        return f"{self.restaurant.name} — {self.label}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date must be on or after start date.")

    def save(self, *args, **kwargs):
        if not self.label:
            self.label = str(self.start_date.year)
        self.full_clean(validate_unique=True, validate_constraints=True)
        super().save(*args, **kwargs)


class RestaurantStaff(models.Model):
    class Role(models.TextChoices):
        RESTAURANT_ADMIN = "restaurant_admin", "Restaurant admin"
        STAFF = "staff", "Staff"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="restaurant_profile",
    )
    restaurant = models.ForeignKey(
        Restaurant,
        on_delete=models.CASCADE,
        related_name="staff_members",
    )
    role = models.CharField(
        max_length=32,
        choices=Role.choices,
        default=Role.STAFF,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["restaurant", "user__username"]

    def __str__(self):
        return f"{self.user.get_username()} @ {self.restaurant.name}"

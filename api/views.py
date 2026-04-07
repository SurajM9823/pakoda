from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


CATEGORIES = [
    {"id": 1, "name": "Special Pakoda"},
    {"id": 2, "name": "Fast Food"},
    {"id": 3, "name": "Snacks"},
    {"id": 4, "name": "Pizza"},
    {"id": 5, "name": "Main Course"},
    {"id": 6, "name": "Appetizers"},
    {"id": 7, "name": "Chiya & Coffee"},
    {"id": 8, "name": "Fresh Juice & Drinks"},
]


def _build_products():
    products = []
    base_price = 120
    for i in range(1, 101):
        category = CATEGORIES[(i - 1) % len(CATEGORIES)]
        products.append(
            {
                "id": i,
                "name": f"Product {i:03d} - {category['name']}",
                "category_id": category["id"],
                "category": category["name"],
                "price_npr": base_price + ((i - 1) % 10) * 10,
            }
        )
    return products


PRODUCTS = _build_products()


@api_view(["GET"])
@permission_classes([AllowAny])
def health_view(_request):
    return Response({"status": "ok", "service": "pakoda-by-kilo-api"})


@api_view(["GET"])
@permission_classes([AllowAny])
def categories_view(_request):
    return Response({"count": len(CATEGORIES), "results": CATEGORIES})


@api_view(["GET"])
@permission_classes([AllowAny])
def products_view(request):
    category_id = request.query_params.get("category_id")
    if not category_id:
        return Response({"count": len(PRODUCTS), "results": PRODUCTS})

    try:
        category_id = int(category_id)
    except ValueError:
        return Response({"count": 0, "results": [], "error": "Invalid category_id"})

    filtered = [p for p in PRODUCTS if p["category_id"] == category_id]
    return Response({"count": len(filtered), "results": filtered})

from .utils import restaurant_for_request


class ActiveRestaurantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_restaurant = restaurant_for_request(request)
        return self.get_response(request)

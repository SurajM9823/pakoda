from django.shortcuts import render


def _page(request, template: str, nav_page: str):
    return render(request, template, {"nav_page": nav_page})


def home(request):
    return _page(request, "web/home.html", "index")


def about(request):
    return _page(request, "web/about.html", "about")


def service(request):
    return _page(request, "web/service.html", "service")


def menu(request):
    return _page(request, "web/menu.html", "menu")


def contact(request):
    return _page(request, "web/contact.html", "contact")


def reservation(request):
    return _page(request, "web/reservation.html", "reservation")


def testimonial(request):
    return _page(request, "web/testimonial.html", "testimonial")

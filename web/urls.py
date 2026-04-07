from django.urls import path

from . import views

app_name = "web"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("service/", views.service, name="service"),
    path("menu/", views.menu, name="menu"),
    path("contact/", views.contact, name="contact"),
    path("reservation/", views.reservation, name="reservation"),
    path("testimonial/", views.testimonial, name="testimonial"),
]

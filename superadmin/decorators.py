from functools import wraps
from urllib.parse import urlencode

from django.shortcuts import redirect


def superadmin_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            q = urlencode({"next": request.get_full_path()})
            return redirect(f"/superadmin/login/?{q}")
        if not request.user.is_superuser:
            return redirect("portal:dashboard")
        return view_func(request, *args, **kwargs)

    return wrapper

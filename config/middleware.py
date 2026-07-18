class DedupeOriginMiddleware:
    """
    Some front-end proxies (e.g. OpenLiteSpeed) forward the Origin header
    duplicated (comma-joined) due to a proxy bug. Django's CsrfViewMiddleware
    expects a single value, so collapse it to the first non-empty part here,
    before CSRF validation runs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.META.get("HTTP_ORIGIN")
        if origin and "," in origin:
            parts = [p.strip() for p in origin.split(",") if p.strip()]
            if parts:
                request.META["HTTP_ORIGIN"] = parts[0]
        return self.get_response(request)

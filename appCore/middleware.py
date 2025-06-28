from .models import APILog


class APILogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.excluded_paths = ["/api/docs/", "/api/schema/"]

    def __call__(self, request):
        response = self.get_response(request)

        if request.path.startswith("/api/") and not any(
            request.path.startswith(excluded) for excluded in self.excluded_paths
        ):
            try:
                request_data = request.body.decode("utf-8") if request.body else ""
                response_data = getattr(response, "content", b"").decode("utf-8")
                APILog.objects.create(
                    path=request.path,
                    method=request.method,
                    status_code=response.status_code,
                    user=str(request.user) if request.user.is_authenticated else None,
                    request_data=request_data,
                    response_data=response_data,
                )
            except Exception as e:
                print(f"Logging error: {e}")

        return response

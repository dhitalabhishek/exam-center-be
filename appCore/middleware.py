from .models import APILog
from django.utils.deprecation import MiddlewareMixin


class APILogMiddleware(MiddlewareMixin):
    def _init_(self, get_response=None):
        self.get_response = get_response
        self.excluded_paths = ["/api/docs/", "/api/schema/"]
        # Call parent constructor for MiddlewareMixin compatibility
        super()._init_(get_response)

    def process_request(self, request):
        # Store original body for later use
        if hasattr(request, 'body'):
            request._cached_body = request.body
        
    def process_response(self, request, response):
        if request.path.startswith("/api/") and not any(
            request.path.startswith(excluded) for excluded in self.excluded_paths
        ):
            try:
                # Get request data
                request_data = ""
                if hasattr(request, '_cached_body') and request._cached_body:
                    request_data = request._cached_body.decode("utf-8")
                elif request.POST:
                    request_data = str(dict(request.POST))
                elif request.GET:
                    request_data = str(dict(request.GET))
                
                # Get response data
                response_data = getattr(response, "content", b"").decode("utf-8")
                
                APILog.objects.create(
                    path=request.path,
                    method=request.method,
                    status_code=response.status_code,
                    user=str(request.user) if hasattr(request, 'user') and request.user.is_authenticated else None,
                    request_data=request_data,
                    response_data=response_data,
                )
            except Exception as e:
                print(f"Logging error: {e}")
        
        return response
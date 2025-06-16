import base64

from django.contrib.admin.views.decorators import staff_member_required
from django.core.files.base import ContentFile
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render

from appAuthentication.models import Candidate


@staff_member_required
def webcam_capture_view(request):
    context = {}

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "search":
            # Handle search functionality
            search_query = request.POST.get("search_query", "").strip()
            candidates = []

            if search_query:
                # Search by symbol number or name
                candidates = Candidate.objects.filter(
                    Q(symbol_number__icontains=search_query)
                    | Q(first_name__icontains=search_query)
                    | Q(last_name__icontains=search_query)
                    | Q(email__icontains=search_query),
                )[:10]  # Limit to 10 results

            context["candidates"] = candidates
            context["search_query"] = search_query

        elif action == "capture":
            # Handle image capture and save
            candidate_id = request.POST.get("candidate_id")
            image_data = request.POST.get("image_data")

            candidate = get_object_or_404(Candidate, id=candidate_id)

            if image_data:
                format, imgstr = image_data.split(";base64,")
                ext = format.split("/")[-1]
                candidate.profile_image.save(
                    f"{candidate.symbol_number}_photo.{ext}",
                    ContentFile(base64.b64decode(imgstr)),
                    save=True,
                )
                context["success"] = True
                context["selected_candidate"] = candidate

    return render(request, "admin/appAuthentication/candidate/webcapture.html", context)


@staff_member_required
def get_candidate_details(request):
    """AJAX endpoint to get candidate details"""
    if request.method == "GET":
        candidate_id = request.GET.get("candidate_id")
        try:
            candidate = Candidate.objects.get(id=candidate_id)
            data = {
                "id": candidate.id,
                "symbol_number": candidate.symbol_number,
                "first_name": candidate.first_name,
                "last_name": candidate.last_name,
                "email": candidate.email,
                "phone": getattr(candidate, "phone", ""),
                "constituency": getattr(candidate, "constituency", ""),
                "party": getattr(candidate, "party", ""),
                "profile_image_url": candidate.profile_image.url
                if candidate.profile_image
                else None,
            }
            return JsonResponse(data)
        except Candidate.DoesNotExist:
            return JsonResponse({"error": "Candidate not found"}, status=404)

    return JsonResponse({"error": "Invalid request"}, status=400)

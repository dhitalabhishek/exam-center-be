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
            # Handle normal HTML search
            search_query = request.POST.get("search_query", "").strip()
            candidates = []

            if search_query:
                candidates = Candidate.objects.filter(
                    Q(symbol_number__icontains=search_query)
                    | Q(first_name__icontains=search_query)
                    | Q(last_name__icontains=search_query)
                    | Q(email__icontains=search_query),
                )[:10]

            context["candidates"] = candidates
            context["search_query"] = search_query
            return render(
                request,
                "admin/appAuthentication/candidate/webcapture.html",
                context,
            )

        if action == "capture":
            # Return JSON for webcam capture
            candidate_id = request.POST.get("candidate_id")
            image_data = request.POST.get("image_data")

            candidate = get_object_or_404(Candidate, id=candidate_id)

            if image_data:
                try:
                    format, imgstr = image_data.split(";base64,")  # noqa: A001
                    ext = format.split("/")[-1]
                    candidate.profile_image.save(
                        f"{candidate.symbol_number}_photo.{ext}",
                        ContentFile(base64.b64decode(imgstr)),
                        save=True,
                    )
                    return JsonResponse({"success": True, "candidate_id": candidate.id})
                except Exception as e:  # noqa: BLE001
                    return JsonResponse({"success": False, "error": str(e)}, status=400)

            return JsonResponse(
                {"success": False, "error": "No image data provided"},
                status=400,
            )

        if action == "biometric":
            # Return JSON for biometric upload
            candidate_id = request.POST.get("candidate_id")
            bitmap_data = request.POST.get("bitmap_data")  # base64
            hand = request.POST.get("hand")  # 'left' or 'right'

            candidate = get_object_or_404(Candidate, id=candidate_id)

            if bitmap_data and hand in ["left", "right"]:
                try:
                    _, imgstr = bitmap_data.split(",", 1)
                    file = ContentFile(
                        base64.b64decode(imgstr),
                        name=f"{candidate.symbol_number}_{hand}.bmp",
                    )

                    if hand == "left":
                        candidate.fingerprint_left.save(file.name, file, save=True)
                    else:
                        candidate.fingerprint_right.save(file.name, file, save=True)

                    return JsonResponse(
                        {"success": True, "hand": hand, "candidate_id": candidate.id},
                    )
                except Exception as e:  # noqa: BLE001
                    return JsonResponse({"success": False, "error": str(e)}, status=400)

            return JsonResponse(
                {"success": False, "error": "Invalid bitmap or hand"},
                status=400,
            )

    # GET or no-action POST fallback
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
                "institute": candidate.institute.name,
                "program": candidate.program,
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

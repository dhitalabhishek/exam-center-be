# from django.utils.timezone import now
# from rest_framework import status
# from rest_framework.decorators import api_view
# from rest_framework.response import Response

# from appAuthentication.models import Candidate
# from appExam.models import ExamEvent as Event


# @api_view(["GET"])
# def upcoming_events(request):
#     upcoming = Event.objects.filter(date__gte=now().date()).order_by("date")
#     data = [
#         {
#             "id": event.id,
#             "name": event.name,
#             "date": event.date,
#             "shifts": [
#                 {"id": shift.id, "start_time": shift.start_time}
#                 for shift in event.shifts.all()
#             ],
#         }
#         for event in upcoming
#     ]
#     return Response(data)


# @api_view(["GET"])
# def student_event_info(request, student_id):
#     try:
#         candidate = Candidate.objects.get(pk=student_id)
#         shift = candidate.assigned_shift
#         event = shift.event
#         data = {
#             "student": candidate.symbol_number,
#             "shift": {
#                 "id": shift.id,
#                 "start_time": shift.start_time,
#             },
#             "event": {
#                 "id": event.id,
#                 "name": event.name,
#                 "date": event.date,
#             },
#         }
#         return Response(data)
#     except Candidate.DoesNotExist:
#         return Response(
#             {"detail": "Candidate not found"}, status=status.HTTP_404_NOT_FOUND,
#         )
#     except Exception:
#         return Response(
#             {"detail": "Shift/Event info not found"}, status=status.HTTP_404_NOT_FOUND,
#         )

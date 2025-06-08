import asyncio
import json
from datetime import timezone
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.paginator import Paginator
from rest_framework_simplejwt.exceptions import InvalidToken
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import UntypedToken

from appExam.models import Answer
from appExam.models import Candidate
from appExam.models import Question
from appExam.models import StudentAnswer
from appExam.models import StudentExamEnrollment
from config.settings.local import SECRET_KEY

User = get_user_model()

class ExamConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Extract token from query string
        query_string = self.scope["query_string"].decode()
        query_params = parse_qs(query_string)
        token = query_params.get("token")
        if token:
            token = token[0]  # get first token if multiple

        if not token:
            await self.close(code=403)
            return

        # Verify token and get user
        try:
            UntypedToken(token)  # Validate token (raises if invalid)
            # You can get user id from token if you decode it manually
            # For now, let's decode manually:
            from rest_framework_simplejwt.backends import TokenBackend
            token_backend = TokenBackend(algorithm="HS256", signing_key=SECRET_KEY)
            valid_data = token_backend.decode(token, verify=True)
            user_id = valid_data["user_id"]
            user = await database_sync_to_async(User.objects.get)(id=user_id)
            self.scope["user"] = user
            self.user = user
        except (InvalidToken, TokenError, User.DoesNotExist):
            await self.close(code=403)
            return

        # Accept the connection if authenticated
        await self.accept()

    async def disconnect(self, close_code):
        # Cancel the background task when the socket disconnects
        if hasattr(self, "time_task"):
            self.time_task.cancel()
            try:  # noqa: SIM105
                await self.time_task
            except asyncio.CancelledError:
                pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get("action")

            if action == "get_question":
                page = data.get("page", 1)
                response = await self.get_paginated_question(page)
                await self.send(text_data=json.dumps(response))

            elif action == "save_answer":
                question_id = data.get("question_id")
                answer_id = data.get("answer_id")
                response = await self.save_answer(question_id, answer_id)
                await self.send(text_data=json.dumps(response))

            elif action == "get_exam_session":
                response = await self.get_exam_session()
                await self.send(text_data=json.dumps(response))

            elif action == "get_answers_summary":
                response = await self.get_answers_summary()
                await self.send(text_data=json.dumps(response))

            elif action == "start_timer":
                # Start the time remaining loop
                if not hasattr(self, "time_task") or self.time_task.done():
                    self.time_task = asyncio.create_task(self.send_time_remaining_loop())

            elif action == "stop_timer":
                # Stop the time remaining loop
                if hasattr(self, "time_task"):
                    self.time_task.cancel()

        except Exception as e:  # noqa: BLE001
            await self.send(text_data=json.dumps({"error": str(e), "status": 500}))

    async def send_time_remaining_loop(self):
        try:
            while True:
                time_data = await self.get_time_remaining()
                await self.send(
                    text_data=json.dumps({"type": "time_remaining", "data": time_data}),
                )
                await asyncio.sleep(1)  # send every 1 second
        except asyncio.CancelledError:
            pass  # task cancelled on disconnect

    @database_sync_to_async
    def get_time_remaining(self):
        try:
            candidate = Candidate.objects.get(user=self.user)
            enrollment = StudentExamEnrollment.objects.select_related("session").get(
                candidate=candidate,
            )
            now = timezone.now()
            end_time = enrollment.session.end_time
            remaining = end_time - now

            if remaining.total_seconds() <= 0:
                return {"seconds": 0, "expired": True}

            return {"seconds": int(remaining.total_seconds()), "expired": False}

        except Exception as e:  # noqa: BLE001
            return {"seconds": 0, "expired": True, "error": str(e)}

    @database_sync_to_async
    def get_exam_session(self):
        """Get exam session details - equivalent to get_exam_session_view"""
        try:
            candidate = Candidate.objects.get(user=self.user)
            enrollment = StudentExamEnrollment.objects.select_related(
                "session",
                "session__exam",
                "session__exam__program",
                "session__exam__subject",
                "hall_assignment",
                "hall_assignment__hall",
            ).get(candidate=candidate)

            session = enrollment.session
            exam = session.exam

            # Count total questions for this session
            total_questions = Question.objects.filter(session=session).count()

            # Calculate duration
            duration_minutes = None
            if session.start_time and session.end_time:
                duration = session.end_time - session.start_time
                duration_minutes = int(duration.total_seconds() // 60)

            # Get time remaining for this specific candidate
            time_remaining_minutes = None
            if enrollment.time_remaining:
                time_remaining_minutes = int(
                    enrollment.time_remaining.total_seconds() // 60,
                )

            # Build response data
            session_data = {
                "session_id": session.id,
                "exam_id": exam.id,
                "exam_title": str(exam),
                "program": exam.program.name,
                "subject": exam.subject.name if exam.subject else None,
                "total_marks": exam.total_marks,
                "description": exam.description,
                "start_time": session.start_time.isoformat()
                if session.start_time
                else None,
                "end_time": session.end_time.isoformat() if session.end_time else None,
                "duration_minutes": duration_minutes,
                "time_remaining_minutes": time_remaining_minutes,
                "total_questions": total_questions,
                "notice": session.notice,
                "status": session.status,
                "hall_name": enrollment.hall_assignment.hall.name
                if enrollment.hall_assignment
                else None,
                "seat_range": enrollment.hall_assignment.roll_number_range
                if enrollment.hall_assignment
                else None,
            }

            return {
                "data": session_data,
                "message": "Exam session details retrieved successfully",
                "error": None,
                "status": 200,
            }

        except Candidate.DoesNotExist:
            return {"error": "Candidate profile not found", "status": 404}
        except StudentExamEnrollment.DoesNotExist:
            return {"error": "No exam enrollment found for this candidate", "status": 404}
        except Exception as e:
            return {"error": str(e), "status": 500}

    @database_sync_to_async
    def get_paginated_question(self, page):
        """Get paginated question with student's previous answer"""
        try:
            candidate = Candidate.objects.get(user=self.user)
            enrollment = StudentExamEnrollment.objects.select_related("session").get(candidate=candidate)

            question_order = enrollment.question_order
            answer_order = enrollment.answer_order

            if not question_order:
                return {
                    "error": "Questions not yet randomized for this candidate",
                    "status": 400,
                }

            page_size = 1
            paginator = Paginator(question_order, page_size)

            if page > paginator.num_pages:
                return {
                    "error": "Page number out of range",
                    "status": 404,
                }

            question_id = paginator.get_page(page).object_list[0]
            question = Question.objects.get(id=question_id)

            randomized_answer_ids = answer_order.get(str(question_id), [])

            answers_data = []
            for answer_id in randomized_answer_ids:
                try:
                    answer = Answer.objects.get(id=answer_id)
                    answers_data.append({
                        "id": answer.id,
                        "text": answer.text,
                    })
                except Answer.DoesNotExist:
                    continue

            # Get student's previous answer for this question (if any)
            student_answer = None
            try:
                student_answer_obj = StudentAnswer.objects.get(
                    enrollment=enrollment,
                    question=question,
                )
                student_answer = {
                    "selected_answer_id": student_answer_obj.selected_answer.id if student_answer_obj.selected_answer else None,
                    "is_answered": student_answer_obj.selected_answer is not None,
                }
            except StudentAnswer.DoesNotExist:
                student_answer = {
                    "selected_answer_id": None,
                    "is_answered": False,
                }

            return {
                "data": {
                    "question": {
                        "id": question.id,
                        "text": question.text,
                        "answers": answers_data,
                        "student_answer": student_answer,  # Added student answer info
                    },
                    "pagination": {
                        "current_page": page,
                        "page_size": page_size,
                        "total_pages": paginator.num_pages,
                        "total_questions": len(question_order),
                        "has_next": paginator.page(page).has_next(),
                        "has_previous": paginator.page(page).has_previous(),
                        "next_page": page + 1 if paginator.page(page).has_next() else None,
                        "previous_page": page - 1 if paginator.page(page).has_previous() else None,
                    },
                },
                "message": "Question retrieved successfully",
                "status": 200,
            }

        except Candidate.DoesNotExist:
            return {"error": "Candidate not found", "status": 404}
        except StudentExamEnrollment.DoesNotExist:
            return {"error": "Enrollment not found", "status": 404}
        except Question.DoesNotExist:
            return {"error": "Question not found", "status": 404}
        except Exception as e:
            return {"error": str(e), "status": 500}

    @database_sync_to_async
    def save_answer(self, question_id, answer_id):
        """Save student answer with proper validation"""
        try:
            candidate = Candidate.objects.get(user=self.user)
            enrollment = StudentExamEnrollment.objects.select_related("session").get(
                candidate=candidate,
            )

            if not question_id:
                return {"error": "question_id is required", "status": 400}

            # Validate that the question belongs to this exam session
            try:
                question = Question.objects.get(
                    id=question_id,
                    session=enrollment.session,
                )
            except Question.DoesNotExist:
                return {
                    "error": "Question not found or doesn't belong to your exam session",
                    "status": 404,
                }

            # Validate the answer if provided
            selected_answer = None
            if answer_id:
                try:
                    selected_answer = Answer.objects.get(
                        id=answer_id,
                        question=question,
                    )
                except Answer.DoesNotExist:
                    return {
                        "error": "Answer not found or doesn't belong to the specified question",
                        "status": 404,
                    }

            # Create or update the student answer
            student_answer, created = StudentAnswer.objects.update_or_create(
                enrollment=enrollment,  # Fixed: use enrollment instead of candidate
                question=question,      # Fixed: use question object instead of question_id
                defaults={
                    "selected_answer": selected_answer,  # Fixed: use selected_answer instead of answer_id
                },
            )

            # Prepare response message
            if created:
                message = "Answer saved successfully"
            elif selected_answer:
                message = "Answer updated successfully"
            else:
                message = "Answer cleared successfully"

            return {
                "data": {
                    "question_id": question.id,
                    "selected_answer_id": selected_answer.id if selected_answer else None,
                    "is_answered": selected_answer is not None,
                    "created": created,
                },
                "message": message,
                "error": None,
                "status": 200,
            }

        except Candidate.DoesNotExist:
            return {"error": "Candidate profile not found", "status": 404}
        except StudentExamEnrollment.DoesNotExist:
            return {"error": "No exam enrollment found for this candidate", "status": 404}
        except Exception as e:
            return {"error": str(e), "status": 500}

    @database_sync_to_async
    def get_answers_summary(self):
        """Get summary of all student answers - equivalent to get_student_answers_summary_view"""
        try:
            candidate = Candidate.objects.get(user=self.user)
            enrollment = StudentExamEnrollment.objects.select_related("session").get(
                candidate=candidate,
            )

            # Get all student answers for this enrollment
            student_answers = StudentAnswer.objects.filter(
                enrollment=enrollment,
            ).select_related("question", "selected_answer")

            # Get the randomized question order for this candidate
            question_order = enrollment.question_order
            total_questions = len(question_order)

            # Build summary data
            answers_summary = []
            answered_count = 0

            for question_id in question_order:
                question_answered = False
                selected_answer_id = None

                # Find if this question has been answered
                for student_answer in student_answers:
                    if student_answer.question.id == question_id:
                        if student_answer.selected_answer:
                            question_answered = True
                            selected_answer_id = student_answer.selected_answer.id
                            answered_count += 1
                        break

                answers_summary.append({
                    "question_id": question_id,
                    "is_answered": question_answered,
                    "selected_answer_id": selected_answer_id,
                })

            return {
                "data": {
                    "answers": answers_summary,
                    "total_questions": total_questions,
                    "answered_count": answered_count,
                    "unanswered_count": total_questions - answered_count,
                    "completion_percentage": round((answered_count / total_questions) * 100, 2) if total_questions > 0 else 0,
                },
                "message": "Student answers summary retrieved successfully",
                "error": None,
                "status": 200,
            }

        except Candidate.DoesNotExist:
            return {"error": "Candidate profile not found", "status": 404}
        except StudentExamEnrollment.DoesNotExist:
            return {"error": "No exam enrollment found for this candidate", "status": 404}
        except Exception as e:
            return {"error": str(e), "status": 500}

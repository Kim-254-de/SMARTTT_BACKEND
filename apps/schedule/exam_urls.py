from django.urls import path

from .exam_views import MyExamDutiesView, MyExamsView

urlpatterns = [
    path("my/", MyExamsView.as_view(), name="my-exams"),
    path("my-duties/", MyExamDutiesView.as_view(), name="my-exam-duties"),
]

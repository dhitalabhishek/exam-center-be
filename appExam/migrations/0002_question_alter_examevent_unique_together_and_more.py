# Generated by Django 5.1.9 on 2025-05-30 09:35

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appAuthentication', '0002_candidate_exam_status_candidate_verification_status'),
        ('appExam', '0001_initial'),
        ('appInstitutions', '0002_institute_address_institute_logo_institute_phone_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='Question',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
            ],
        ),
        migrations.AlterUniqueTogether(
            name='examevent',
            unique_together=None,
        ),
        migrations.RemoveField(
            model_name='examevent',
            name='hall',
        ),
        migrations.RemoveField(
            model_name='examevent',
            name='schedule',
        ),
        migrations.RemoveField(
            model_name='examevent',
            name='shift',
        ),
        migrations.AddField(
            model_name='hall',
            name='location',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name='hall',
            name='capacity',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='hall',
            name='name',
            field=models.CharField(max_length=255),
        ),
        migrations.CreateModel(
            name='Exam',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('duration_minutes', models.PositiveIntegerField()),
                ('total_marks', models.PositiveIntegerField()),
                ('description', models.TextField(blank=True)),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appInstitutions.program')),
                ('subject', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='appInstitutions.subject')),
            ],
        ),
        migrations.CreateModel(
            name='ExamSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_time', models.DateTimeField()),
                ('status', models.CharField(choices=[('scheduled', 'Scheduled'), ('ongoing', 'Ongoing'), ('completed', 'Completed'), ('cancelled', 'Cancelled')], default='scheduled', max_length=30)),
                ('roll_number_start', models.CharField(max_length=20)),
                ('roll_number_end', models.CharField(max_length=20)),
                ('exam', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appExam.exam')),
            ],
        ),
        migrations.CreateModel(
            name='HallAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hall', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appExam.hall')),
                ('program', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appInstitutions.program')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='hall_allocations', to='appExam.examsession')),
                ('subject', models.ForeignKey(blank=True, help_text='Required if exam has a subject', null=True, on_delete=django.db.models.deletion.SET_NULL, to='appInstitutions.subject')),
            ],
        ),
        migrations.CreateModel(
            name='Answer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('text', models.TextField()),
                ('is_correct', models.BooleanField(default=False)),
                ('question', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='answers', to='appExam.question')),
            ],
        ),
        migrations.CreateModel(
            name='QuestionSet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255)),
                ('hall_allocation', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='question_sets', to='appExam.hallallocation')),
                ('program', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='appInstitutions.program')),
                ('subject', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='appInstitutions.subject')),
            ],
        ),
        migrations.AddField(
            model_name='question',
            name='question_set',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='questions', to='appExam.questionset'),
        ),
        migrations.CreateModel(
            name='StudentExamEnrollment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('exam_started_at', models.DateTimeField(blank=True, null=True)),
                ('exam_ended_at', models.DateTimeField(blank=True, null=True)),
                ('candidate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appAuthentication.candidate')),
                ('hall_allocation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appExam.hallallocation')),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appExam.examsession')),
            ],
        ),
        migrations.DeleteModel(
            name='CandidateAssignment',
        ),
        migrations.DeleteModel(
            name='Schedule',
        ),
        migrations.DeleteModel(
            name='ExamEvent',
        ),
        migrations.DeleteModel(
            name='Shift',
        ),
    ]

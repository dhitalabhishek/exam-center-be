# Generated by Django 5.1.9 on 2025-06-02 09:57

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appExam', '0012_alter_studentexamenrollment_time_remaining'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='question',
            constraint=models.UniqueConstraint(fields=('session', 'text'), name='unique_session_text'),
        ),
    ]

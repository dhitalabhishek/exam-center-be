# Generated by Django 5.1.9 on 2025-06-12 07:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appExam', '0018_examsession_created_at_examsession_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentexamenrollment',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='studentexamenrollment',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]

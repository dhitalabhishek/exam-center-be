# Generated by Django 5.1.9 on 2025-06-01 09:45

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appExam', '0010_rename_hallassignment_hallandstudentassignment_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='session',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='appExam.examsession'),
        ),
    ]

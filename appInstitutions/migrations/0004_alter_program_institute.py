# Generated by Django 5.1.9 on 2025-06-01 09:48

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('appInstitutions', '0003_remove_program_duration_years'),
    ]

    operations = [
        migrations.AlterField(
            model_name='program',
            name='institute',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='programs', to='appInstitutions.institute'),
        ),
    ]

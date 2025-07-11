# Generated by Django 5.1.9 on 2025-06-04 11:37

from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='CeleryTask',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('task_id', models.CharField(max_length=255, unique=True)),
                ('name', models.CharField(max_length=255)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('STARTED', 'Started'), ('RETRY', 'Retrying'), ('FAILURE', 'Failed'), ('SUCCESS', 'Succeeded')], default='PENDING', max_length=50)),
                ('progress', models.PositiveSmallIntegerField(default=0)),
                ('message', models.TextField(blank=True)),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('updated', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Celery Task',
                'verbose_name_plural': 'Celery Tasks',
                'ordering': ['-created'],
            },
        ),
    ]

from django.db import models


class Institute(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=14, blank=True)
    description = models.TextField(blank=True)
    address = models.TextField(blank=True)
    logo = models.ImageField(upload_to="institutes/photos/", blank=True)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=500)
    code = models.CharField(max_length=50, unique=True)
    institute = models.ForeignKey(
        Institute, on_delete=models.CASCADE, related_name="subjects",
    )
    description = models.TextField(blank=True)
    credits = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Program(models.Model):
    name = models.CharField(max_length=255)
    institute = models.ForeignKey(
        Institute, on_delete=models.CASCADE, related_name="programs",
    )
    subjects = models.ManyToManyField(Subject, blank=True, related_name="programs")
    description = models.TextField(blank=True)
    duration_years = models.PositiveIntegerField(default=4)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

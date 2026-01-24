from django.db import models


class Parent(models.Model):
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    is_active = models.BooleanField(default=True)
    date = models.DateField(null=True, blank=True)

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class Child(models.Model):
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE)
    date = models.DateField()

    def __str__(self) -> str:  # pragma: no cover
        return self.name

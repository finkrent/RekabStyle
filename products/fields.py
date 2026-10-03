from django.db import models
from django.db.models import QuerySet
from django.utils.text import slugify


class AutoSlugField(models.SlugField):
    def __init__(self, *args, unique_scope=(), **kwargs):
        self.unique_scope = tuple(unique_scope)
        kwargs.setdefault("blank", True)
        kwargs.setdefault("default", "")
        kwargs.setdefault("editable", True)
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.unique_scope:
            kwargs["unique_scope"] = self.unique_scope
        return name, path, args, kwargs

    def pre_save(self, model_instance, add):
        slug = getattr(model_instance, self.attname)
        if not slug:
            slug = self.make_slug(model_instance)
            setattr(model_instance, self.attname, slug)
        return slug

    def make_slug(self, instance, reserved=()):
        base_slug = slugify(instance.name, allow_unicode=self.allow_unicode) or "item"
        slug = base_slug
        suffix = 2
        scope = {
            field_name: getattr(instance, field_name)
            for field_name in self.unique_scope
        }

        while slug in reserved or self.model._default_manager.filter(
            **scope, **{self.name: slug}
        ).exclude(pk=instance.pk).exists():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        return slug


class AutoSlugQuerySet(QuerySet):
    def bulk_create(self, objs, **kwargs):
        objs = list(objs)
        reserved_by_scope = {}
        for obj in objs:
            for field in obj._meta.fields:
                if not isinstance(field, AutoSlugField):
                    continue
                scope = tuple(
                    getattr(obj, f"{field_name}_id", getattr(obj, field_name))
                    for field_name in field.unique_scope
                )
                reserved = reserved_by_scope.setdefault((field, scope), set())
                slug = getattr(obj, field.attname)
                if not slug:
                    slug = field.make_slug(obj, reserved)
                    setattr(obj, field.attname, slug)
                reserved.add(slug)
        return super().bulk_create(objs, **kwargs)


AutoSlugManager = models.Manager.from_queryset(AutoSlugQuerySet)

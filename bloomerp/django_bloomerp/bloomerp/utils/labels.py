from django.db.models import Model


def safe_object_label(obj) -> str:
    if isinstance(obj, Model) or hasattr(obj, "_meta"):
        return _safe_model_label(obj)
    return str(obj)


def _safe_model_label(obj) -> str:
    fallback = f"{obj._meta.verbose_name.title()} {obj.pk}"
    try:
        label = str(obj)
    except Exception:
        return fallback

    if "error in __str__" in label or "maximum recursion depth exceeded" in label:
        return fallback
    return label

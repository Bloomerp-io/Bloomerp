from django.http import HttpRequest
from django.template.loader import render_to_string

from bloomerp.communication.builtins.in_app_notifications.base import (
    BaseSystemMessageType,
    SystemMessageItemData,
)


class GeneralSystemMessage(BaseSystemMessageType):
    @classmethod
    def build_item_data(cls, data: dict) -> SystemMessageItemData:
        severity = str(data.get("severity") or "info").lower()
        default_titles = {
            "success": "Success",
            "info": "Information",
            "warning": "Warning",
            "error": "Error",
        }
        return SystemMessageItemData(
            title=str(data.get("title") or default_titles.get(severity, "Message")),
            snippet=str(data.get("message") or ""),
            raw_meta_data={"severity": severity},
        )

    @classmethod
    def render(cls, item, request: HttpRequest | None = None) -> str:
        return render_to_string(
            "inbox_items/general_system_message.html",
            {"item": item, "severity": (item.raw_meta_data or {}).get("severity", "info")},
            request=request,
        )

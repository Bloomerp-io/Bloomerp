import bleach
from bs4 import BeautifulSoup
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

from bloomerp.workspaces.base import BaseTileRenderer
from bloomerp.workspaces.text_tile.model import TextTileConfig


MARKDOWN_RENDERER = MarkdownIt(
    "commonmark",
    {
        "breaks": True,
        "html": False,
    },
).enable("table")

ALLOWED_TAGS = [
    "a",
    "blockquote",
    "br",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "rel", "target"],
}
ALLOWED_PROTOCOLS = ["http", "https", "mailto"]
TAG_CLASSES = {
    "h1": ["text-3xl", "font-semibold", "tracking-tight", "text-slate-900", "mt-1", "mb-3"],
    "h2": ["text-2xl", "font-semibold", "tracking-tight", "text-slate-900", "mt-1", "mb-3"],
    "h3": ["text-xl", "font-semibold", "text-slate-900", "mt-1", "mb-2"],
    "h4": ["text-lg", "font-semibold", "text-slate-900", "mt-1", "mb-2"],
    "h5": ["text-base", "font-semibold", "text-slate-900", "mt-1", "mb-2"],
    "h6": ["text-sm", "font-semibold", "uppercase", "tracking-wide", "text-slate-700", "mt-1", "mb-2"],
    "p": ["my-3", "leading-7", "text-slate-700"],
    "ul": ["my-3", "list-disc", "pl-5", "space-y-1"],
    "ol": ["my-3", "list-decimal", "pl-5", "space-y-1"],
    "li": ["leading-7", "text-slate-700"],
    "blockquote": ["my-4", "border-l-2", "border-slate-200", "pl-4", "italic", "text-slate-600"],
    "pre": ["my-4", "overflow-x-auto", "rounded-lg", "bg-slate-950", "p-3", "text-sm", "text-slate-100"],
    "code": ["rounded", "bg-slate-100", "px-1", "py-0.5", "text-[0.95em]"],
    "table": ["my-4", "w-full", "border-collapse", "text-left", "text-sm"],
    "thead": ["bg-slate-50"],
    "th": ["border", "border-slate-200", "p-2", "font-medium", "text-slate-800"],
    "td": ["border", "border-slate-200", "p-2", "text-slate-700"],
    "a": ["text-blue-600", "underline-offset-2"],
    "hr": ["my-4", "border-slate-200"],
}


def _apply_markdown_classes(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag_name, classes in TAG_CLASSES.items():
        for element in soup.find_all(tag_name):
            existing_classes = element.get("class", [])
            element["class"] = [*existing_classes, *classes]

            if tag_name == "a":
                element["target"] = "_blank"
                element["rel"] = "noopener noreferrer"

            if tag_name == "code" and element.parent and element.parent.name == "pre":
                element["class"] = [cls for cls in element.get("class", []) if cls not in TAG_CLASSES["code"]]
                element["class"] += ["bg-transparent", "p-0", "text-inherit"]

    return str(soup)


def render_markdown(markdown: str) -> str:
    rendered = MARKDOWN_RENDERER.render(markdown or "")
    cleaned = bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
    )
    linkified = bleach.linkify(cleaned)
    return _apply_markdown_classes(linkified)


class TextTileRenderer(BaseTileRenderer):
    template_name = "cotton/workspaces/tiles/text.html"

    @classmethod
    def render(cls, config: TextTileConfig, user) -> str:
        return cls.render_to_string(
            {
                "config": config,
                "rendered_markdown": mark_safe(render_markdown(config.markdown)),
            }
        )

import {
    $createParagraphNode,
    $createTextNode,
    $getSelection,
    $isElementNode,
    $isRangeSelection,
    type LexicalEditor,
    type LexicalNode,
} from "lexical";
import { $createHeadingNode } from "@lexical/rich-text";
import { $createListItemNode, $createListNode } from "@lexical/list";
import { $createTableNodeWithDimensions } from "@lexical/table";

export type TemplateField = {
    name: string;
    label: string;
    type: string;
    token: string;
};

export type TemplateBuilderBlockSectionId = "text" | "layout" | "merge";

export type TemplateBuilderBlockExecutionContext = {
    editor: LexicalEditor;
    focusEditor: () => void;
    insertBlockNode: (node: LexicalNode) => void;
    promptImageUpload: () => void;
};

export type TemplateBuilderBlockAction =
    | {
        kind: "direct";
        run: (context: TemplateBuilderBlockExecutionContext) => void;
    }
    | {
        kind: "prompt";
        run: (context: TemplateBuilderBlockExecutionContext) => void;
    };

export type TemplateBuilderBlockDefinition = {
    id: string;
    sectionId: TemplateBuilderBlockSectionId;
    label: string;
    description: string;
    icon?: string;
    keywords?: string[];
    action: TemplateBuilderBlockAction;
};

export type TemplateBuilderBlockSectionDefinition = {
    id: TemplateBuilderBlockSectionId;
    title: string;
};

export type TemplateBuilderResolvedBlockSection = TemplateBuilderBlockSectionDefinition & {
    blocks: TemplateBuilderBlockDefinition[];
};

export const TEMPLATE_BUILDER_BLOCK_SECTIONS: TemplateBuilderBlockSectionDefinition[] = [
    { id: "text", title: "Text" },
    { id: "layout", title: "Layout" },
];

function insertHeadingBlock(
    context: TemplateBuilderBlockExecutionContext,
    type: "h1" | "h2",
    text: string,
    style = ""
): void {
    context.focusEditor();
    context.editor.update(() => {
        const heading = $createHeadingNode(type);
        if (style) {
            heading.setStyle(style);
        }
        heading.append($createTextNode(text));
        context.insertBlockNode(heading);
    });
    context.focusEditor();
}

function insertParagraphBlock(
    context: TemplateBuilderBlockExecutionContext,
    text: string,
    style = ""
): void {
    context.focusEditor();
    context.editor.update(() => {
        const paragraph = $createParagraphNode();
        if (style) {
            paragraph.setStyle(style);
        }
        paragraph.append($createTextNode(text));
        context.insertBlockNode(paragraph);
    });
    context.focusEditor();
}

function insertTableBlock(
    context: TemplateBuilderBlockExecutionContext,
    rows: number,
    columns: number,
    includeHeaders: boolean,
    cellText: string[][]
): void {
    context.focusEditor();
    context.editor.update(() => {
        const table = $createTableNodeWithDimensions(rows, columns, includeHeaders);

        table.getChildren().forEach((row, rowIndex) => {
            if (!$isElementNode(row)) return;

            row.getChildren().forEach((cell, columnIndex) => {
                if (!$isElementNode(cell)) return;

                const paragraph = cell.getFirstChild();
                if (!$isElementNode(paragraph)) return;

                paragraph.clear();
                paragraph.append($createTextNode(cellText[rowIndex]?.[columnIndex] || ""));
            });
        });

        context.insertBlockNode(table);
    });
    context.focusEditor();
}

function insertListBlock(
    context: TemplateBuilderBlockExecutionContext,
    type: "bullet" | "number"
): void {
    context.focusEditor();
    context.editor.update(() => {
        const list = $createListNode(type);
        const item = $createListItemNode();
        const paragraph = $createParagraphNode();
        paragraph.append($createTextNode(""));
        item.append(paragraph);
        list.append(item);
        context.insertBlockNode(list);
    });
    context.focusEditor();
}

function insertMergeField(context: TemplateBuilderBlockExecutionContext, token: string): void {
    context.editor.update(() => {
        const selection = $getSelection();
        if ($isRangeSelection(selection)) {
            selection.insertText(token);
            return;
        }

        const paragraph = $createParagraphNode();
        paragraph.append($createTextNode(token));
        context.insertBlockNode(paragraph);
    });
    context.focusEditor();
}

export const BUILT_IN_TEMPLATE_BUILDER_BLOCKS: TemplateBuilderBlockDefinition[] = [
    {
        id: "heading-1",
        sectionId: "text",
        label: "Title",
        description: "Large page title",
        icon: "fa-solid fa-heading",
        keywords: ["heading", "title", "hero", "h1"],
        action: {
            kind: "direct",
            run: (context) => insertHeadingBlock(
                context,
                "h1",
                "Document title",
                "margin:0 0 12px;font-size:30pt;line-height:1.05;font-weight:700;"
            ),
        },
    },
    {
        id: "heading-2",
        sectionId: "text",
        label: "Section heading",
        description: "Major section title",
        icon: "fa-solid fa-heading",
        keywords: ["heading", "section", "h2"],
        action: {
            kind: "direct",
            run: (context) => insertHeadingBlock(
                context,
                "h2",
                "Section heading",
                "margin:0 0 10px;font-size:18pt;line-height:1.2;font-weight:700;"
            ),
        },
    },
    {
        id: "paragraph",
        sectionId: "text",
        label: "Paragraph",
        description: "Body text block",
        icon: "fa-solid fa-paragraph",
        keywords: ["text", "copy", "body", "paragraph"],
        action: {
            kind: "direct",
            run: (context) => insertParagraphBlock(
                context,
                "Write your content here.",
                "margin:0 0 14px;"
            ),
        },
    },
    {
        id: "divider",
        sectionId: "layout",
        label: "Divider",
        description: "Horizontal divider",
        icon: "fa-solid fa-minus",
        keywords: ["rule", "separator", "line", "divider"],
        action: {
            kind: "direct",
            run: (context) => insertParagraphBlock(
                context,
                "------------------------------------------------------------",
                "margin:0 0 20px;color:#cbd5e1;" 
            ),
        },
    },
    {
        id: "table",
        sectionId: "layout",
        label: "Table",
        description: "Two-column table",
        icon: "fa-solid fa-table",
        keywords: ["table", "grid", "rows", "columns"],
        action: {
            kind: "direct",
            run: (context) => insertTableBlock(context, 3, 2, true, [
                ["Label", "Value"],
                ["Row 1", "Details"],
                ["Row 2", "Details"],
            ]),
        },
    },
    {
        id: "columns",
        sectionId: "layout",
        label: "Columns",
        description: "Two-column section",
        icon: "fa-solid fa-columns",
        keywords: ["columns", "two column", "layout"],
        action: {
            kind: "direct",
            run: (context) => insertTableBlock(context, 1, 2, false, [["Left column", "Right column"]]),
        },
    },
    {
        id: "image",
        sectionId: "layout",
        label: "Image",
        description: "Upload image",
        icon: "fa-solid fa-image",
        keywords: ["image", "photo", "picture", "media"],
        action: {
            kind: "prompt",
            run: (context) => context.promptImageUpload(),
        },
    },
    {
        id: "bullet-list",
        sectionId: "layout",
        label: "Bullet list",
        description: "Simple bullet list",
        icon: "fa-solid fa-list-ul",
        keywords: ["list", "bullets", "unordered"],
        action: {
            kind: "direct",
            run: (context) => insertListBlock(context, "bullet"),
        },
    },
    {
        id: "number-list",
        sectionId: "layout",
        label: "Numbered list",
        description: "Simple numbered list",
        icon: "fa-solid fa-list-ol",
        keywords: ["list", "numbered", "ordered"],
        action: {
            kind: "direct",
            run: (context) => insertListBlock(context, "number"),
        },
    },
];

function getMergeFieldIcon(type: string): string {
    const normalizedType = type.trim().toLowerCase();

    if (normalizedType.includes("date") || normalizedType.includes("time")) {
        return "fa-solid fa-calendar-day";
    }

    if (normalizedType.includes("email")) {
        return "fa-solid fa-envelope";
    }

    if (normalizedType.includes("url") || normalizedType.includes("link")) {
        return "fa-solid fa-link";
    }

    if (
        normalizedType.includes("bool") ||
        normalizedType.includes("checkbox") ||
        normalizedType.includes("toggle")
    ) {
        return "fa-solid fa-circle-check";
    }

    if (
        normalizedType.includes("int") ||
        normalizedType.includes("float") ||
        normalizedType.includes("decimal") ||
        normalizedType.includes("number")
    ) {
        return "fa-solid fa-hashtag";
    }

    if (normalizedType.includes("image") || normalizedType.includes("file")) {
        return "fa-solid fa-file-image";
    }

    if (normalizedType.includes("user") || normalizedType.includes("person")) {
        return "fa-solid fa-user";
    }

    return "fa-solid fa-tag";
}

export function createMergeFieldBlocks(fields: TemplateField[]): TemplateBuilderBlockDefinition[] {
    return fields.map((field) => ({
        id: `merge-${field.name}`,
        sectionId: "merge",
        label: field.label,
        description: `Insert ${field.token}`,
        icon: getMergeFieldIcon(field.type),
        keywords: [field.name, field.type, field.token],
        action: {
            kind: "direct",
            run: (context) => insertMergeField(context, field.token),
        },
    }));
}

export function resolveTemplateBuilderSections(
    fields: TemplateField[]
): TemplateBuilderResolvedBlockSection[] {
    const allBlocks = [...BUILT_IN_TEMPLATE_BUILDER_BLOCKS, ...createMergeFieldBlocks(fields)];

    return TEMPLATE_BUILDER_BLOCK_SECTIONS.map((section) => ({
        ...section,
        blocks: allBlocks.filter((block) => block.sectionId === section.id),
    }));
}

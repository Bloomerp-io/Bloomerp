import type { TextFormatType } from "lexical";
import type { ListType } from "@lexical/list";
import { t } from "@/utils/i18n";
import type { BloomerpTextEditor } from "./BloomerpTextEditor";
import type { Action, ActionContext, ActionPayload, ActionState, ActionSurface } from "./actionRegistry";
import {
    $changeIndent, $clearTextFormatting, $setAlignment, $setBlockFormat, $setListFormat,
    $setTextStyle, $toggleTextFormat, canConvertToCode, getBlockState, getTextFormatState,
    textActionState, type Alignment, type BlockFormat,
} from "./formatting";

const SURFACES: readonly ActionSurface[] = ["toolbar", "selection", "slash", "shortcut"];

/** Resolve labels after the active translation catalog has loaded. */
function labels(): Record<string, string> {
    return {
        bold: t("Bold"), italic: t("Italic"), underline: t("Underline"), strikethrough: t("Strikethrough"),
        inline_code: t("Inline code"), highlight: t("Highlight"), clear_formatting: t("Clear formatting"),
        paragraph: t("Paragraph"), h1: t("Heading 1"), h2: t("Heading 2"), h3: t("Heading 3"),
        quote: t("Quote"), code_block: t("Code Block"), unordered_list: t("Bullet List"),
        ordered_list: t("Numbered List"), checklist: t("Checklist"), text_color: t("Text color"),
        font_size: t("Font size"), align_left: t("Align left"), align_center: t("Align center"),
        align_right: t("Align right"), align_justify: t("Justify"), indent: t("Increase indent"), outdent: t("Decrease indent"),
    };
}

/** Add common metadata while keeping labels lazy and behavior instance-independent. */
function define(id: string, action: Omit<Action, "label" | "surfaces">): Action {
    return {
        ...action, surfaces: SURFACES,
        /** Resolve this command's label in the current language. */
        get label(): string { return labels()[id]; },
    };
}

/** Build an inline toggle shared by all editor action surfaces. */
function textFormat(id: string, format: TextFormatType, icon: string, shortcuts: string[]): Action {
    /** Toggle selected text in the common registry transaction. */
    function apply(_host: BloomerpTextEditor, context: ActionContext): void { $toggleTextFormat(context, format); }
    /** Report active and mixed selected text formatting. */
    function state(context: ActionContext): ActionState { return getTextFormatState(context, format); }
    return define(id, { icon, group: "text", shortcuts, handler: apply, getState: state });
}

/** Build a semantic block conversion with shared capability checks. */
function blockFormat(id: string, format: BlockFormat, icon: string, shortcuts: string[] = []): Action {
    /** Replace affected blocks while retaining content and layout. */
    function apply(_host: BloomerpTextEditor, context: ActionContext): void { $setBlockFormat(context, format); }
    /** Protect structured content from destructive literal-code conversions. */
    function state(context: ActionContext): ActionState {
        const result = getBlockState(context, format);
        return { ...result, disabled: result.disabled || (format === "code_block" && !canConvertToCode(context)) };
    }
    return define(id, { icon, group: "block", shortcuts, handler: apply, getState: state });
}

/** Build a list conversion which retains valid list-item structure. */
function listFormat(id: string, format: ListType, icon: string, shortcut: string): Action {
    /** Apply Lexical's structural list conversion. */
    function apply(_host: BloomerpTextEditor, context: ActionContext): void { $setListFormat(context, format); }
    /** Detect selected list type and mixed selections. */
    function state(context: ActionContext): ActionState { return getBlockState(context, format); }
    return define(id, { icon, group: "list", shortcuts: [shortcut], handler: apply, getState: state });
}

/** Build alignment as a block property rather than another node type. */
function align(format: Alignment, shortcut: string): Action {
    /** Align each selected text block, including paragraphs inside table cells. */
    function apply(_host: BloomerpTextEditor, context: ActionContext): void { $setAlignment(context, format); }
    /** Read current block alignment for the toolbar and menus. */
    function state(context: ActionContext): ActionState { return getBlockState(context, format, true); }
    return define(`align_${format}`, { icon: `fa-solid fa-align-${format}`, group: "alignment", shortcuts: [shortcut], handler: apply, getState: state });
}

/** Apply structural indentation through existing rich-text commands. */
function indent(direction: "in" | "out"): Action {
    /** Indent the selected blocks in the shared transaction. */
    function apply(_host: BloomerpTextEditor, context: ActionContext): void { $changeIndent(context, direction); }
    /** Disable outdent when all selected blocks have zero indentation. */
    function state(context: ActionContext): ActionState {
        return { disabled: !context.range || !context.blocks.length || (direction === "out" && context.blocks.every(hasNoIndent)) };
    }
    return define(direction === "in" ? "indent" : "outdent", {
        icon: direction === "in" ? "fa-solid fa-indent" : "fa-solid fa-outdent", group: "alignment",
        shortcuts: [direction === "in" ? "mod+]" : "mod+["], handler: apply, getState: state,
    });
}

/** Identify blocks already at the page edge. */
function hasNoIndent(block: import("lexical").ElementNode): boolean { return block.getIndent() === 0; }

/** Remove inline styling while retaining semantic content. */
function clear(_host: BloomerpTextEditor, context: ActionContext): void { $clearTextFormatting(context); }

/** Build a handler which changes only one controlled CSS property. */
function styleHandler(property: string): Action["handler"] {
    /** Apply the selected value without overwriting unrelated text styles. */
    function apply(_host: BloomerpTextEditor, context: ActionContext, payload: ActionPayload): void {
        $setTextStyle(context, property, payload.value ?? "");
    }
    return apply;
}

/** Supply the same built-in formatting capabilities to every editor instance. */
export function createFormattingActions(): Readonly<Record<string, Action>> {
    return {
        paragraph: blockFormat("paragraph", "paragraph", "fa-solid fa-paragraph", ["mod+shift+0"]),
        h1: blockFormat("h1", "h1", "fa-solid fa-heading", ["mod+shift+1"]),
        h2: blockFormat("h2", "h2", "fa-solid fa-heading", ["mod+shift+2"]),
        h3: blockFormat("h3", "h3", "fa-solid fa-heading", ["mod+shift+3"]),
        quote: blockFormat("quote", "quote", "fa-solid fa-quote-right", ["mod+shift+>"]),
        code_block: blockFormat("code_block", "code_block", "fa-solid fa-code", ["mod+shift+c"]),
        bold: textFormat("bold", "bold", "fa-solid fa-bold", ["mod+b"]),
        italic: textFormat("italic", "italic", "fa-solid fa-italic", ["mod+i"]),
        strikethrough: textFormat("strikethrough", "strikethrough", "fa-solid fa-strikethrough", ["mod+shift+x"]),
        underline: textFormat("underline", "underline", "fa-solid fa-underline", ["mod+u"]),
        inline_code: textFormat("inline_code", "code", "fa-solid fa-code", ["mod+e"]),
        highlight: textFormat("highlight", "highlight", "fa-solid fa-highlighter", ["mod+shift+h"]),
        text_color: define("text_color", { icon: "fa-solid fa-palette", group: "text", handler: styleHandler("color"), getState: textActionState,
            /** Translate palette names when the menu opens. */
            get options(): import("./actionRegistry").ActionOption[] { return [
                { label: t("Default"), value: "" }, { label: t("Red"), value: "#dc2626" },
                { label: t("Orange"), value: "#ea580c" }, { label: t("Green"), value: "#16a34a" },
                { label: t("Blue"), value: "#2563eb" }, { label: t("Purple"), value: "#9333ea" },
                { label: t("Custom color…"), value: "#000000", input: "color" },
            ]; },
        }),
        font_size: define("font_size", { icon: "fa-solid fa-text-height", group: "text", handler: styleHandler("font-size"), getState: textActionState,
            /** Resolve the default label while retaining language-independent size values. */
            get options(): import("./actionRegistry").ActionOption[] { return [
                { label: t("Default"), value: "" }, ...["10px", "12px", "14px", "16px", "18px", "24px", "32px"].map(sizeOption),
            ]; },
        }),
        clear_formatting: define("clear_formatting", { icon: "fa-solid fa-eraser", group: "text", shortcuts: ["mod+\\"], handler: clear, getState: textActionState }),
        unordered_list: listFormat("unordered_list", "bullet", "fa-solid fa-list-ul", "mod+shift+8"),
        ordered_list: listFormat("ordered_list", "number", "fa-solid fa-list-ol", "mod+shift+7"),
        checklist: listFormat("checklist", "check", "fa-solid fa-list-check", "mod+shift+9"),
        align_left: align("left", "mod+shift+l"), align_center: align("center", "mod+shift+e"),
        align_right: align("right", "mod+shift+r"), align_justify: align("justify", "mod+shift+j"),
        indent: indent("in"), outdent: indent("out"),
    };
}

/** Describe a font size with the same display and persisted CSS value. */
function sizeOption(value: string): import("./actionRegistry").ActionOption { return { label: value, value }; }

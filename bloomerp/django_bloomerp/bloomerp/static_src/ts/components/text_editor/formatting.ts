import {
    $createParagraphNode, $isElementNode, $isTextNode, INDENT_CONTENT_COMMAND,
    OUTDENT_CONTENT_COMMAND, type ElementNode, type RangeSelection, type TextFormatType,
} from "lexical";
import { $createHeadingNode, $createQuoteNode, type HeadingTagType } from "@lexical/rich-text";
import { $createListNode, $isListItemNode, $isListNode, insertList, type ListType } from "@lexical/list";
import { $patchStyleText } from "@lexical/selection";
import { $createCodeBlockNode } from "./nodes/CodeBlockNode";
import type { ActionContext, ActionState } from "./actionRegistry";

export type BlockFormat = "paragraph" | "quote" | "code_block" | HeadingTagType;
export type Alignment = "left" | "center" | "right" | "justify";

/** Report uniform or mixed formatting without including immutable reference labels. */
export function getTextFormatState(context: ActionContext, format: TextFormatType): ActionState {
    const values = context.range?.isCollapsed()
        ? [context.range.hasFormat(format)]
        : context.textNodes.map(readFormat);
    /** Read this specific format from one selected ordinary text node. */
    function readFormat(node: import("lexical").TextNode): boolean { return node.hasFormat(format); }
    return { ...textActionState(context), active: values.length > 0 && values.every(isTrue), mixed: values.some(isTrue) && !values.every(isTrue) };
}

/** Identify true formatting flags for consistent toggling of mixed selections. */
function isTrue(value: boolean): boolean { return value; }

/** Extract exact selected leaves without retaining Lexical 0.18's mutated node cache. */
function $extractText(selection: RangeSelection): import("lexical").LexicalNode[] {
    const backward = selection.isBackward();
    selection.setCachedNodes(null);
    const nodes = [...selection.extract()];
    selection.setCachedNodes(null);
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if ($isTextNode(first) && $isTextNode(last)) {
        if (backward) selection.setTextNodeRange(last, last.getTextContentSize(), first, 0);
        else selection.setTextNodeRange(first, 0, last, last.getTextContentSize());
    }
    return nodes;
}

/** Restrict inline formatting to text ranges outside literal source-code blocks. */
export function textActionState(context: ActionContext): ActionState {
    return { disabled: !context.range || context.blocks.some(isCodeBlock)
        || (!context.range.isCollapsed() && context.textNodes.length === 0) };
}

/** Identify literal code among the blocks touched by the current range. */
function isCodeBlock(block: ElementNode): boolean { return block.getType() === "text-editor-code-block"; }

/** Toggle exactly the selected characters, retaining atomic mentions and link containers. */
export function $toggleTextFormat(context: ActionContext, format: TextFormatType): void {
    const selection = context.range;
    if (!selection) return;
    if (selection.isCollapsed()) { selection.formatText(format); return; }
    const active = Boolean(getTextFormatState(context, format).active);
    const nodes = $extractText(selection);
    for (const node of nodes) {
        if ($isTextNode(node) && node.isSimpleText() && node.hasFormat(format) === active) node.toggleFormat(format);
    }
    const first = nodes.find(isSimpleText);
    if ($isTextNode(first)) selection.format = first.getFormat();
}

/** Select ordinary text leaves without changing reference entities. */
function isSimpleText(node: import("lexical").LexicalNode): boolean { return $isTextNode(node) && node.isSimpleText(); }

/** Apply an allowed CSS property to selected text or to subsequent typing at the caret. */
export function $setTextStyle(context: ActionContext, property: string, value: string): void {
    const selection = context.range;
    if (!selection) return;
    if (selection.isCollapsed()) { $patchStyleText(selection, { [property]: value || null }); return; }
    for (const node of $extractText(selection)) {
        if (!$isTextNode(node) || !node.isSimpleText()) continue;
        const style = document.createElement("span").style;
        style.cssText = node.getStyle();
        if (value) style.setProperty(property, value);
        else style.removeProperty(property);
        node.setStyle(style.cssText);
    }
}

/** Remove inline formatting while retaining semantic links, references, and block structure. */
export function $clearTextFormatting(context: ActionContext): void {
    const selection = context.range;
    if (!selection) return;
    if (!selection.isCollapsed()) {
        for (const node of $extractText(selection)) {
            if ($isTextNode(node) && node.isSimpleText()) node.setFormat(0).setStyle("");
        }
    }
    selection.format = 0;
    selection.setStyle("");
}

/** Describe the selected block's semantic type for controls and toggle state. */
export function getBlockFormat(block: ElementNode): string {
    if (block.getType() === "heading") return (block as import("@lexical/rich-text").HeadingNode).getTag();
    if ($isListItemNode(block) && $isListNode(block.getParent())) return block.getParent<import("@lexical/list").ListNode>()!.getListType();
    return isCodeBlock(block) ? "code_block" : block.getType();
}

/** Report disabled block conversions and mixed block, list, or alignment values. */
export function getBlockState(context: ActionContext, value: string, alignment: boolean = false): ActionState {
    const formats = context.blocks.map(readValue);
    /** Read semantic block type or normalized paragraph alignment. */
    function readValue(block: ElementNode): string {
        return alignment ? block.getFormatType() || "left" : getBlockFormat(block);
    }
    return { disabled: !context.range || formats.length === 0,
        active: formats.length > 0 && formats.every(matches), mixed: formats.some(matches) && !formats.every(matches) };
    /** Compare a block's state with the command represented by this control. */
    function matches(format: string): boolean { return format === value; }
}

/** Create the semantic replacement without copying arbitrary DOM markup. */
function $createBlock(format: BlockFormat): ElementNode {
    if (format === "paragraph") return $createParagraphNode();
    if (format === "quote") return $createQuoteNode();
    if (format === "code_block") return $createCodeBlockNode();
    return $createHeadingNode(format);
}

/** Convert only selected list items, splitting their list around untouched siblings. */
function $replaceListItem(block: ElementNode, replacement: ElementNode): void {
    const list = block.getParent();
    if (!$isListNode(list)) return;
    const following = block.getNextSiblings();
    list.insertAfter(replacement);
    if (following.length) {
        const after = $createListNode(list.getListType(), $isListItemNode(following[0]) ? following[0].getValue() : 1);
        after.append(...following);
        replacement.insertAfter(after);
    }
    for (const child of block.getChildren()) {
        if ($isListNode(child)) replacement.insertAfter(child);
        else replacement.append(child);
    }
    block.remove();
    if (list.isEmpty()) list.remove();
}

/** Transform selected blocks while preserving their text, alignment, indent, and references. */
export function $setBlockFormat(context: ActionContext, format: BlockFormat): void {
    for (const block of context.blocks) {
        if (!block.isAttached()) continue;
        const replacement = $createBlock(format);
        replacement.setFormat(block.getFormatType()).setIndent(block.getIndent()).setDirection(block.getDirection());
        if ($isListItemNode(block)) $replaceListItem(block, replacement);
        else block.replace(replacement, true);
    }
}

/** Convert paragraphs and existing lists through Lexical's list-specific structural rules. */
export function $setListFormat(context: ActionContext, type: ListType): void { insertList(context.editor, type); }

/** Align selected text blocks without replacing their semantic node types. */
export function $setAlignment(context: ActionContext, alignment: Alignment): void {
    for (const block of context.blocks) block.setFormat(alignment);
}

/** Use Lexical's indentation commands so list nesting and paragraph indentation remain valid. */
export function $changeIndent(context: ActionContext, direction: "in" | "out"): void {
    context.editor.dispatchCommand(direction === "in" ? INDENT_CONTENT_COMMAND : OUTDENT_CONTENT_COMMAND, undefined);
}

/** Prevent a literal code conversion from flattening semantic references, images, or HTML. */
export function canConvertToCode(context: ActionContext): boolean { return !context.blocks.some(containsProtectedContent); }

/** Inspect a full affected block because a partial text selection still converts that whole block. */
function containsProtectedContent(node: import("lexical").LexicalNode): boolean {
    if (["bloomerp-reference", "bloomerp-file-image", "text-editor-image", "text-editor-html"].includes(node.getType())) return true;
    return $isElementNode(node) && node.getChildren().some(containsProtectedContent);
}

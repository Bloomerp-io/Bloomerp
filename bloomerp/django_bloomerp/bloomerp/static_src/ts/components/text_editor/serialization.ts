import {
    $isElementNode, $isTextNode, ParagraphNode, TextNode,
    type DOMConversion, type DOMConversionMap, type DOMConversionOutput,
    type DOMExportOutput, type HTMLConfig, type LexicalEditor, type LexicalNode,
} from "lexical";
import { HeadingNode, QuoteNode } from "@lexical/rich-text";
import { ListItemNode, ListNode } from "@lexical/list";
import { CodeBlockNode } from "./nodes/CodeBlockNode";

const TEXT_STYLES = ["color", "background-color", "font-size"];

/** Export layout and inline formatting as portable HTML shared by reloading and PDF generation. */
function exportFormatting(editor: LexicalEditor, node: LexicalNode): DOMExportOutput {
    const output = node.exportDOM(editor);
    if (!(output.element instanceof HTMLElement)) return output;
    if ($isElementNode(node)) {
        const alignment = node.getFormatType();
        if (alignment) output.element.style.textAlign = alignment;
        if (node.getIndent()) {
            output.element.style.textIndent = "";
            output.element.style.paddingInlineStart = `${node.getIndent() * 40}px`;
        }
    } else if ($isTextNode(node)) {
        const style = document.createElement("span").style;
        style.cssText = node.getStyle();
        for (const property of TEXT_STYLES) {
            const value = style.getPropertyValue(property);
            if (value) output.element.style.setProperty(property, value);
        }
        if (node.hasFormat("highlight")) {
            output.element.style.backgroundColor ||= "#fef08a";
            output.element.style.color ||= "inherit";
        }
    }
    return output;
}

/** Extend native importers to retain supported inline styles and block layout metadata. */
export function createEditorHTMLConfig(): HTMLConfig {
    const imports: DOMConversionMap = {};
    const textImports = TextNode.importDOM() ?? {};
    for (const tag of ["span", "b", "strong", "i", "em", "u", "s", "code", "mark", "sub", "sup"]) {
        /** Prefer this style-preserving importer over the ordinary text-element conversion. */
        function convertElement(element: HTMLElement): DOMConversion {
            const native = textImports[tag]?.(element);
            /** Retain native semantic marks before applying allowed CSS properties to text leaves. */
            function convert(source: HTMLElement): DOMConversionOutput {
                const output = native?.conversion(source) ?? { node: null };
                const original = output.forChild;
                /** Preserve reference-node identity while restoring ordinary text styles. */
                function decorate(child: LexicalNode, parent: LexicalNode | null | undefined): LexicalNode | null {
                    const node = original ? original(child, parent) : child;
                    if (!$isTextNode(node) || !node.isSimpleText()) return node;
                    const style = document.createElement("span").style;
                    style.cssText = node.getStyle();
                    for (const property of TEXT_STYLES) {
                        const value = source.style.getPropertyValue(property);
                        if (tag === "mark" && property === "background-color" && value === "rgb(254, 240, 138)") continue;
                        if (value) style.setProperty(property, value);
                    }
                    if (tag === "mark" && !node.hasFormat("highlight")) node.toggleFormat("highlight");
                    if (node.hasFormat("highlight") && style.backgroundColor === "rgb(254, 240, 138)") style.removeProperty("background-color");
                    node.setStyle(style.cssText);
                    return node;
                }
                return { ...output, forChild: decorate };
            }
            return { priority: 1, conversion: convert };
        }
        imports[tag] = convertElement;
    }
    const classes = [ParagraphNode, HeadingNode, QuoteNode, ListNode, ListItemNode, CodeBlockNode];
    for (const nodeClass of classes) {
        for (const [tag, importer] of Object.entries(nodeClass.importDOM() ?? {})) {
            const previous = imports[tag];
            /** Restore layout after the native importer creates the semantic block node. */
            function convertBlock(element: HTMLElement): DOMConversion | null {
                const native = importer(element);
                const fallback = previous?.(element) ?? null;
                if (!native) return fallback;
                if (fallback && (fallback.priority ?? 0) > (native.priority ?? 0)) return fallback;
                /** Preserve alignment and indentation through a saved-HTML reload. */
                function convert(source: HTMLElement): DOMConversionOutput {
                    const output = native.conversion(source);
                    if (output && !Array.isArray(output.node) && $isElementNode(output.node)) {
                        const alignment = source.style.textAlign;
                        if (["left", "start", "center", "right", "end", "justify"].includes(alignment)) {
                            output.node.setFormat(alignment as import("lexical").ElementFormatType);
                        }
                        const indent = Number.parseFloat(source.style.paddingInlineStart || source.style.paddingLeft);
                        if (Number.isFinite(indent)) output.node.setIndent(Math.max(0, Math.round(indent / 40)));
                    }
                    return output;
                }
                return { priority: Math.min(4, (native.priority ?? 0) + 1) as DOMConversion["priority"], conversion: convert };
            }
            imports[tag] = convertBlock;
        }
    }
    const exports: NonNullable<HTMLConfig["export"]> = new Map();
    for (const nodeClass of [TextNode, ...classes]) exports.set(nodeClass, exportFormatting);
    return { import: imports, export: exports };
}

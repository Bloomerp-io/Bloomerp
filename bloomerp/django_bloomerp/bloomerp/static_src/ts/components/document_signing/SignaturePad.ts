import BaseComponent, { getComponent } from "../BaseComponent";
import type { Modal } from "../Modal";
import { t } from "../../utils/i18n";

type Point = [number, number];

export interface DrawnSignature {
    type: "drawn";
    version: 1;
    strokes: Point[][];
}

/** Parse only bounded, visible handwriting strokes rather than text or uploaded images. */
export function parseDrawnSignature(value: unknown): DrawnSignature | null {
    try {
        const candidate = (typeof value === "string" ? JSON.parse(value) : value) as Partial<DrawnSignature> | null;
        if (!candidate || candidate.type !== "drawn" || candidate.version !== 1 || !Array.isArray(candidate.strokes)
            || !candidate.strokes.length || candidate.strokes.length > 100) return null;
        const strokes: Point[][] = [];
        let count = 0;
        let length = 0;
        let left = 1, right = 0, top = 1, bottom = 0;
        for (const stroke of candidate.strokes) {
            if (!Array.isArray(stroke) || stroke.length < 2 || (count += stroke.length) > 10000) return null;
            const points: Point[] = [];
            for (const point of stroke) {
                if (!Array.isArray(point) || point.length !== 2 || typeof point[0] !== "number" || typeof point[1] !== "number"
                    || !Number.isFinite(point[0]) || !Number.isFinite(point[1]) || point[0] < 0 || point[0] > 1 || point[1] < 0 || point[1] > 1) return null;
                const position: Point = [Number(point[0].toFixed(6)), Number(point[1].toFixed(6))];
                left = Math.min(left, position[0]); right = Math.max(right, position[0]);
                top = Math.min(top, position[1]); bottom = Math.max(bottom, position[1]);
                const previous = points[points.length - 1];
                if (previous) length += Math.hypot(position[0] - previous[0], (position[1] - previous[1]) * 0.3);
                points.push(position);
            }
            strokes.push(points);
        }
        return length >= 0.02 && Math.max(right - left, (bottom - top) * 0.3) >= 0.01
            ? { type: "drawn", version: 1, strokes } : null;
    } catch { return null; }
}

/** Own one field's drawing pad, vector preview and hidden JSON value through PDF zoom changes. */
export default class SignaturePad extends BaseComponent {
    private lifecycle = new AbortController();
    private modal: Modal;
    private canvas: HTMLCanvasElement;
    private input: HTMLInputElement;
    private button: HTMLButtonElement;
    private error: HTMLElement;
    private strokes: Point[][] = [];
    private pointer: number | null = null;
    private pointCount = 0;
    private required = true;
    private initialized = false;
    private destroyed = false;

    /** Materialize a private modal usable both inside the app and on public invitation pages. */
    public initialize(): void {
        if (!this.element || this.initialized) return;
        this.initialized = true;
        this.required = this.element.dataset.required === "true";
        this.input = this.element.querySelector<HTMLInputElement>("[data-signature-value]")!;
        this.button = this.element.querySelector<HTMLButtonElement>("[data-signature-open]")!;
        const template = this.element.querySelector<HTMLTemplateElement>("[data-signature-modal]")!;
        const declaration = template.content.firstElementChild!.cloneNode(true) as HTMLElement;
        document.body.append(declaration);
        this.modal = getComponent(declaration) as Modal;
        const body = this.modal.getBodyElement()!;
        this.canvas = body.querySelector<HTMLCanvasElement>("[data-signature-canvas]")!;
        this.error = body.querySelector<HTMLElement>("[data-signature-error]")!;
        const options = { signal: this.lifecycle.signal };
        this.button.addEventListener("click", this.open, options);
        body.querySelector("[data-signature-clear]")?.addEventListener("click", this.clear, options);
        body.querySelector("[data-signature-cancel]")?.addEventListener("click", this.cancel, options);
        body.querySelector("[data-signature-apply]")?.addEventListener("click", this.apply, options);
        this.canvas.addEventListener("pointerdown", this.onPointerDown, options);
        this.canvas.addEventListener("pointermove", this.onPointerMove, options);
        this.canvas.addEventListener("pointerup", this.onPointerUp, options);
        this.canvas.addEventListener("pointercancel", this.onPointerCancel, options);
        document.addEventListener("htmx:beforeCleanupElement", this.onCleanup, options);
        if (!this.value) this.input.value = "";
        this.preview();
    }

    /** Return a validated copy of the committed strokes for the signing payload. */
    public get value(): DrawnSignature | null {
        return parseDrawnSignature(this.input.value);
    }

    /** Open the pad when a required field is empty or contains an invalid representation. */
    public validate(): boolean {
        if (this.value || (!this.required && !this.input.value.trim())) return true;
        this.open();
        this.error.hidden = false;
        return false;
    }

    /** Start an editable copy so cancelling leaves the previously committed signature intact. */
    private open = (): void => {
        if (this.button.disabled || this.destroyed) return;
        this.strokes = this.value?.strokes ?? [];
        this.pointCount = 0;
        for (const stroke of this.strokes) this.pointCount += stroke.length;
        this.pointer = null;
        this.error.hidden = true;
        this.modal.setOpener(this.button);
        this.modal.open();
        this.paint();
        this.canvas.focus({ preventScroll: true });
    };

    /** Clear the editable drawing while leaving the committed value unchanged until confirmation. */
    private clear = (): void => {
        this.strokes = [];
        this.pointCount = 0;
        this.pointer = null;
        this.error.hidden = true;
        this.paint();
    };

    /** Discard drawing edits and restore focus through the normal modal lifecycle. */
    private cancel = (): void => { this.modal.close(); };

    /** Commit visible handwriting, or an explicitly cleared optional signature, to the form. */
    private apply = (): void => {
        const drawing = parseDrawnSignature({ type: "drawn", version: 1, strokes: this.strokes });
        if (!drawing && (this.required || this.strokes.length)) {
            this.error.hidden = false;
            this.canvas.focus({ preventScroll: true });
            return;
        }
        this.input.value = drawing ? JSON.stringify(drawing) : "";
        this.preview();
        this.input.dispatchEvent(new Event("change", { bubbles: true }));
        this.modal.close();
    };

    /** Show vector ink in the PDF field so its preview stays sharp at every zoom level. */
    private preview(): void {
        const svg = this.element.querySelector<SVGSVGElement>("[data-signature-preview]")!;
        const drawing = this.value;
        svg.replaceChildren();
        if (drawing) {
            for (const stroke of drawing.strokes) {
                const path = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
                const points: string[] = [];
                for (const [x, y] of stroke) points.push(`${x * 1000},${y * 300}`);
                path.setAttribute("points", points.join(" "));
                path.setAttribute("fill", "none");
                path.setAttribute("stroke", "#111827");
                path.setAttribute("stroke-width", "3");
                path.setAttribute("stroke-linecap", "round");
                path.setAttribute("stroke-linejoin", "round");
                svg.append(path);
            }
        }
        svg.toggleAttribute("hidden", !drawing);
        this.element.querySelector<HTMLElement>("[data-signature-placeholder]")!.hidden = !!drawing;
        this.button.title = drawing ? t("Redraw signature") : t("Draw signature");
    }

    /** Redraw the editable strokes at a fixed logical resolution, independent of display size. */
    private paint(): void {
        const context = this.canvas.getContext("2d")!;
        context.clearRect(0, 0, 1000, 300);
        context.strokeStyle = "#111827";
        context.lineWidth = 3;
        context.lineCap = "round";
        context.lineJoin = "round";
        for (const stroke of this.strokes) {
            if (!stroke.length) continue;
            context.beginPath();
            context.moveTo(stroke[0][0] * 1000, stroke[0][1] * 300);
            for (const [x, y] of stroke.slice(1)) context.lineTo(x * 1000, y * 300);
            context.stroke();
        }
    }

    /** Append a bounded pointer sample in normalized coordinates without duplicating stationary points. */
    private addPoint(event: PointerEvent): void {
        if (this.pointCount >= 10000) return;
        const rectangle = this.canvas.getBoundingClientRect();
        if (!rectangle.width || !rectangle.height) return;
        const point: Point = [Math.max(0, Math.min(1, (event.clientX - rectangle.left) / rectangle.width)), Math.max(0, Math.min(1, (event.clientY - rectangle.top) / rectangle.height))];
        const stroke = this.strokes[this.strokes.length - 1];
        const previous = stroke[stroke.length - 1];
        if (previous && Math.hypot(point[0] - previous[0], point[1] - previous[1]) < 0.0005) return;
        stroke.push(point);
        this.pointCount += 1;
    }

    /** Capture one mouse, touch or pen pointer while leaving additional touches inactive. */
    private onPointerDown = (event: PointerEvent): void => {
        if (event.button !== 0 || this.pointer !== null || this.strokes.length >= 100 || this.pointCount >= 10000) return;
        event.preventDefault();
        this.pointer = event.pointerId;
        this.strokes.push([]);
        this.addPoint(event);
        this.canvas.setPointerCapture(event.pointerId);
        this.error.hidden = true;
    };

    /** Draw only the active pointer, keeping touch scrolling disabled inside the pad. */
    private onPointerMove = (event: PointerEvent): void => {
        if (event.pointerId !== this.pointer) return;
        event.preventDefault();
        this.addPoint(event);
        this.paint();
    };

    /** Finish pen strokes and dots while leaving empty-drawing rejection to validation. */
    private onPointerUp = (event: PointerEvent): void => {
        if (event.pointerId !== this.pointer) return;
        this.addPoint(event);
        const stroke = this.strokes[this.strokes.length - 1];
        if (stroke.length === 1 && this.pointCount < 10000) {
            stroke.push([stroke[0][0], stroke[0][1]]);
            this.pointCount += 1;
        } else if (stroke.length < 2) { this.pointCount -= stroke.length; this.strokes.pop(); }
        this.pointer = null;
        if (this.canvas.hasPointerCapture(event.pointerId)) this.canvas.releasePointerCapture(event.pointerId);
        this.paint();
    };

    /** Discard a cancelled touch stroke while preserving previously completed handwriting. */
    private onPointerCancel = (event: PointerEvent): void => {
        if (event.pointerId !== this.pointer) return;
        this.pointCount -= this.strokes.pop()!.length;
        this.pointer = null;
        this.paint();
    };

    /** Remove the portalled pad when its owning field or signing form is replaced. */
    private onCleanup = (event: Event): void => {
        if ((event as CustomEvent<{ elt?: HTMLElement }>).detail?.elt?.contains(this.element)) this.destroy();
    };

    /** Release pointer listeners and the field-owned modal without retaining form data globally. */
    public override destroy(): void {
        if (this.destroyed) return;
        this.destroyed = true;
        this.lifecycle.abort();
        this.modal?.destroy();
        this.modal?.element?.remove();
        super.destroy();
    }
}

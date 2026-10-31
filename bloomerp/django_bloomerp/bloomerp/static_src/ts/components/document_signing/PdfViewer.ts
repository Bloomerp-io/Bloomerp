import type { PDFDocumentLoadingTask, PDFPageProxy, RenderTask } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { t } from "../../utils/i18n";

interface PdfViewerOptions {
    viewport: HTMLElement;
    pages: HTMLElement;
    zoom: HTMLSelectElement;
    pageClass: string;
    padding: number;
    onPage: (number: number, surface: HTMLElement, scale: number) => void;
    onError: (error: unknown) => void;
    beforeLayout?: () => void;
    afterLayout?: () => void;
    canResize?: () => boolean;
}

/** Own PDF loading, page canvases, zoom and disposable rendering resources for signing screens. */
export default class PdfViewer {
    private loadingTask: PDFDocumentLoadingTask | null = null;
    private pages = new Map<number, PDFPageProxy>();
    private surfaces = new Map<number, HTMLElement>();
    private tasks = new Map<number, RenderTask>();
    private rendered = new Set<number>();
    private visible = new Set<number>();
    private visibility: IntersectionObserver | null = null;
    private resize: ResizeObserver | null = null;
    private resizeTimer: ReturnType<typeof setTimeout> | null = null;
    private generation = 0;
    private viewportWidth = 0;
    private currentScale = 1;
    private fitWidth = false;
    private destroyed = false;

    /** Bind an owning screen's page overlays and controls without creating another component lifecycle. */
    public constructor(private readonly options: PdfViewerOptions) {}

    /** Expose the current display scale without changing persisted field coordinates. */
    public get scale(): number { return this.currentScale; }

    /** Return the loaded page count for navigation and placement validation. */
    public get pageCount(): number { return this.pages.size; }

    /** Check whether a saved placement refers to an existing page. */
    public hasPage(number: number): boolean { return this.pages.has(number); }

    /** Load authenticated PDF bytes and page geometry with the matching bundled worker. */
    public async load(url: string): Promise<void> {
        const pdf = await import("pdfjs-dist");
        if (this.destroyed) return;
        pdf.GlobalWorkerOptions.workerSrc = workerUrl;
        this.loadingTask = pdf.getDocument({ url, withCredentials: true, useSystemFonts: true, useWasm: false });
        const document = await this.loadingTask.promise;
        if (this.destroyed) return;
        for (let number = 1; number <= document.numPages; number += 1) {
            const page = await document.getPage(number);
            if (this.destroyed) return;
            this.pages.set(number, page);
        }
        this.layout();
        this.visible.add(1);
        await this.renderPage(1);
        if (this.destroyed) return;
        this.resize = new ResizeObserver(this.onResize);
        this.resize.observe(this.options.viewport);
    }

    /** Set a bounded percentage zoom and retain custom values in the shared zoom selector. */
    public zoom(scale: number): void {
        if (this.destroyed || !Number.isFinite(scale)) return;
        this.fitWidth = false;
        this.currentScale = Math.max(0.25, Math.min(2.5, scale));
        this.layout();
    }

    /** Reflow the PDF to the owning screen's available width. */
    public fitToWidth(): void {
        this.fitWidth = true;
        this.layout();
    }

    /** Rebuild page surfaces while letting each screen retain and reposition its own controls. */
    private layout = (): void => {
        if (this.destroyed || !this.pages.size) return;
        this.viewportWidth = this.options.viewport.clientWidth;
        const first = this.pages.get(1)!.getViewport({ scale: 1 });
        if (this.fitWidth) this.currentScale = Math.max(0.25, (this.viewportWidth - this.options.padding) / first.width);
        this.generation += 1;
        this.visibility?.disconnect();
        for (const task of this.tasks.values()) task.cancel();
        this.tasks.clear();
        this.rendered.clear();
        this.visible.clear();
        this.surfaces.clear();
        this.options.beforeLayout?.();
        this.options.pages.replaceChildren();
        this.visibility = new IntersectionObserver(this.onVisibility, { root: this.options.viewport, rootMargin: "600px" });
        for (const [number, page] of this.pages) {
            const size = page.getViewport({ scale: this.currentScale });
            const surface = document.createElement("div");
            surface.className = this.options.pageClass;
            surface.dataset.pdfPage = String(number);
            surface.style.width = `${size.width}px`;
            surface.style.height = `${size.height}px`;
            surface.setAttribute("aria-label", `${t("Page")} ${number}`);
            surface.append(document.createElement("canvas"));
            this.options.onPage(number, surface, this.currentScale);
            this.options.pages.append(surface);
            this.surfaces.set(number, surface);
            this.visibility.observe(surface);
        }
        this.updateZoomControl();
        this.options.afterLayout?.();
    };

    /** Keep the selector synchronized with fit width, presets and custom percentage zoom. */
    private updateZoomControl(): void {
        const value = this.fitWidth ? "fit" : String(this.currentScale);
        let found = false;
        for (const option of this.options.zoom.options) if (option.value === value) found = true;
        if (!found) {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = `${Math.round(this.currentScale * 100)}%`;
            this.options.zoom.append(option);
        }
        this.options.zoom.value = value;
    }

    /** Render nearby pages and release offscreen PDF canvases without removing field controls. */
    private onVisibility = (entries: IntersectionObserverEntry[]): void => {
        for (const entry of entries) {
            const number = Number((entry.target as HTMLElement).dataset.pdfPage);
            if (entry.isIntersecting) {
                this.visible.add(number);
                void this.renderPage(number);
            } else {
                this.visible.delete(number);
                if (!this.tasks.has(number)) this.releaseCanvas(number);
            }
        }
    };

    /** Paint a page at device resolution and discard cancelled work from obsolete layouts. */
    private async renderPage(number: number): Promise<void> {
        if (this.destroyed || this.rendered.has(number) || this.tasks.has(number)) return;
        const page = this.pages.get(number);
        const canvas = this.surfaces.get(number)?.querySelector("canvas");
        if (!page || !canvas) return;
        const generation = this.generation;
        const viewport = page.getViewport({ scale: this.currentScale });
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        canvas.width = Math.ceil(viewport.width * ratio);
        canvas.height = Math.ceil(viewport.height * ratio);
        const task = page.render({ canvas, viewport, transform: [ratio, 0, 0, ratio, 0, 0] });
        this.tasks.set(number, task);
        try {
            await task.promise;
            if (generation === this.generation) this.rendered.add(number);
        } catch (error) {
            if (!this.destroyed && generation === this.generation && (error as Error).name !== "RenderingCancelledException") this.options.onError(error);
        } finally {
            if (this.tasks.get(number) === task) this.tasks.delete(number);
            if (generation === this.generation && !this.visible.has(number)) this.releaseCanvas(number);
        }
    }

    /** Release only a page's PDF bitmap so signing inputs and drawn signatures remain intact. */
    private releaseCanvas(number: number): void {
        this.rendered.delete(number);
        const canvas = this.surfaces.get(number)?.querySelector("canvas");
        if (canvas) { canvas.width = 1; canvas.height = 1; }
    }

    /** Debounce width changes while allowing an editor to postpone reflow during a gesture. */
    private onResize = (): void => {
        if (this.destroyed || !this.fitWidth || this.options.canResize?.() === false) return;
        if (Math.abs(this.options.viewport.clientWidth - this.viewportWidth) < 2) return;
        if (this.resizeTimer) clearTimeout(this.resizeTimer);
        this.resizeTimer = setTimeout(this.layout, 120);
    };

    /** Cancel rendering, observers and timers and release the owned PDF worker. */
    public destroy(): void {
        if (this.destroyed) return;
        this.destroyed = true;
        this.generation += 1;
        if (this.resizeTimer) clearTimeout(this.resizeTimer);
        this.visibility?.disconnect();
        this.resize?.disconnect();
        for (const task of this.tasks.values()) task.cancel();
        void this.loadingTask?.destroy();
        this.tasks.clear();
        this.pages.clear();
        this.surfaces.clear();
        this.rendered.clear();
        this.visible.clear();
    }
}

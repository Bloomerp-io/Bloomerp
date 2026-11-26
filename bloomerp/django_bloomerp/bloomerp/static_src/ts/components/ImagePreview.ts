import BaseComponent from './BaseComponent';

const zoomLevels = [1, 1.25, 1.5, 2, 2.5, 3, 4, 5];

export default class ImagePreview extends BaseComponent {
    private lifecycle: AbortController | null = null;
    private resizeObserver: ResizeObserver | null = null;
    private viewport: HTMLElement | null = null;
    private image: HTMLImageElement | null = null;
    private zoomIndex = 0;
    private flipHorizontal = false;
    private flipVertical = false;

    /** Connect the toolbar and fit the image after it loads or the drawer resizes. */
    public override initialize(): void {
        const viewport = this.element?.querySelector<HTMLElement>('[data-image-preview-viewport]');
        const image = viewport?.querySelector('img');
        if (!viewport || !image || !this.element) return;

        this.viewport = viewport;
        this.image = image;
        this.lifecycle = new AbortController();
        const { signal } = this.lifecycle;
        image.addEventListener('load', this.handleLoad, { signal });
        image.addEventListener('error', this.handleError, { signal });
        this.element.addEventListener('click', this.handleControlClick, { signal });
        this.element.addEventListener('htmx:beforeCleanupElement', this.handleCleanup, { signal });
        this.resizeObserver = new ResizeObserver(this.resizeImage);
        this.resizeObserver.observe(viewport);

        if (image.complete) {
            if (image.naturalWidth) this.handleLoad();
            else this.handleError();
        }
    }

    /** Release listeners and observation when HTMX removes the preview. */
    public override destroy(): void {
        this.lifecycle?.abort();
        this.resizeObserver?.disconnect();
        this.lifecycle = null;
        this.resizeObserver = null;
        super.destroy();
    }

    /** Reveal the controls once the image has dimensions. */
    private handleLoad = (): void => {
        this.element?.querySelector('[data-image-preview-controls]')?.removeAttribute('hidden');
        this.updateView();
    };

    /** Offer the original file when the browser cannot display its preview. */
    private handleError = (): void => {
        this.viewport?.setAttribute('hidden', '');
        this.element?.querySelector('[data-image-preview-controls]')?.setAttribute('hidden', '');
        this.element?.querySelector('[data-image-preview-error]')?.removeAttribute('hidden');
    };

    /** Clean up only when the component's own element is being replaced. */
    private handleCleanup = (event: Event): void => {
        if (event.target === this.element) this.destroy();
    };

    /** Apply the selected zoom step, mirror toggle, or reset. */
    private handleControlClick = (event: MouseEvent): void => {
        if (!(event.target instanceof Element)) return;
        const button = event.target.closest<HTMLButtonElement>('[data-image-preview-action]');
        switch (button?.dataset.imagePreviewAction) {
            case 'zoom-out':
                this.zoomIndex = Math.max(0, this.zoomIndex - 1);
                break;
            case 'zoom-in':
                this.zoomIndex = Math.min(zoomLevels.length - 1, this.zoomIndex + 1);
                break;
            case 'flip-horizontal':
                this.flipHorizontal = !this.flipHorizontal;
                break;
            case 'flip-vertical':
                this.flipVertical = !this.flipVertical;
                break;
            case 'reset':
                this.zoomIndex = 0;
                this.flipHorizontal = false;
                this.flipVertical = false;
                break;
            default:
                return;
        }
        this.updateView();
    };

    /** Reflect the current zoom and flip settings in the image and toolbar. */
    private updateView(): void {
        if (!this.image || !this.element) return;
        const zoom = this.element.querySelector<HTMLOutputElement>('[data-image-preview-zoom]');
        const zoomOut = this.element.querySelector<HTMLButtonElement>('[data-image-preview-action="zoom-out"]');
        const zoomIn = this.element.querySelector<HTMLButtonElement>('[data-image-preview-action="zoom-in"]');
        if (zoom) zoom.value = `${zoomLevels[this.zoomIndex] * 100}%`;
        if (zoomOut) zoomOut.disabled = this.zoomIndex === 0;
        if (zoomIn) zoomIn.disabled = this.zoomIndex === zoomLevels.length - 1;
        this.updateFlipButton('flip-horizontal', this.flipHorizontal);
        this.updateFlipButton('flip-vertical', this.flipVertical);
        this.image.style.transform = `scale(${this.flipHorizontal ? -1 : 1}, ${this.flipVertical ? -1 : 1})`;
        this.resizeImage();
    }

    /** Keep each flip button's appearance and pressed state in sync. */
    private updateFlipButton(action: string, pressed: boolean): void {
        const button = this.element?.querySelector(`[data-image-preview-action="${action}"]`);
        button?.setAttribute('aria-pressed', String(pressed));
        button?.classList.toggle('btn-ghost', !pressed);
        button?.classList.toggle('btn-secondary', pressed);
    }

    /** Size the image in the scrollable layout and keep the viewport centered on the same area. */
    private resizeImage = (): void => {
        const { viewport, image } = this;
        if (!viewport?.offsetWidth || !viewport.offsetHeight || !image?.naturalWidth) return;

        const centerX = (viewport.scrollLeft + viewport.clientWidth / 2) / viewport.scrollWidth;
        const centerY = (viewport.scrollTop + viewport.clientHeight / 2) / viewport.scrollHeight;
        const scale = Math.min(1, viewport.offsetWidth / image.naturalWidth, viewport.offsetHeight / image.naturalHeight)
            * zoomLevels[this.zoomIndex];
        image.style.maxWidth = 'none';
        image.style.maxHeight = 'none';
        image.style.width = `${image.naturalWidth * scale}px`;
        image.style.height = `${image.naturalHeight * scale}px`;
        viewport.scrollLeft = centerX * viewport.scrollWidth - viewport.clientWidth / 2;
        viewport.scrollTop = centerY * viewport.scrollHeight - viewport.clientHeight / 2;
    };
}

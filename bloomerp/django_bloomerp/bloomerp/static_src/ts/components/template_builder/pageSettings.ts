import type {
    TemplateBuilderPageOrientation,
    TemplateBuilderPageSettings,
    TemplateBuilderPageSize,
} from "./types";

const PAGE_SIZE_DIMENSIONS: Record<TemplateBuilderPageSize, { width: number; height: number }> = {
    A4: { width: 210, height: 297 },
    Letter: { width: 215.9, height: 279.4 },
    A3: { width: 297, height: 420 },
};

export const DEFAULT_PAGE_SETTINGS: TemplateBuilderPageSettings = {
    pageSize: "A4",
    orientation: "portrait",
    marginInches: 1,
};

export function normalizePageSize(value: string | undefined): TemplateBuilderPageSize {
    if (value === "A3") return "A3";
    if (value === "Letter" || value === "letter") return "Letter";
    return "A4";
}

export function normalizePageOrientation(value: string | undefined): TemplateBuilderPageOrientation {
    return value === "landscape" ? "landscape" : "portrait";
}

export function normalizePageMargin(value: string | number | undefined): number {
    const parsed = typeof value === "number" ? value : Number.parseFloat(value || "");
    if (!Number.isFinite(parsed)) return DEFAULT_PAGE_SETTINGS.marginInches;
    return Math.max(0, Math.min(3, parsed));
}

export function getPageDimensions(settings: TemplateBuilderPageSettings): { width: number; height: number } {
    const base = PAGE_SIZE_DIMENSIONS[settings.pageSize];
    if (settings.orientation === "landscape") {
        return { width: base.height, height: base.width };
    }
    return base;
}

export function getPageWrapperStyle(settings: TemplateBuilderPageSettings): string {
    const dimensions = getPageDimensions(settings);
    const margin = `${settings.marginInches}in`;

    return [
        "box-sizing:border-box",
        `width:${dimensions.width}mm`,
        `min-height:${dimensions.height}mm`,
        "margin:0 auto",
        `padding:${margin}`,
        "background:#ffffff",
        "color:#0f172a",
        "font-family:Georgia, 'Times New Roman', serif",
        "font-size:12pt",
        "line-height:1.6",
    ].join(";");
}

import BaseTile from "./BaseTile";
import { Excalidraw, serializeAsJSON } from "@excalidraw/excalidraw";
import "@excalidraw/excalidraw/index.css";
import { createElement } from "react";
import { createRoot, Root } from "react-dom/client";

export default class Canvas extends BaseTile {
    private root: Root | null = null;

    private onExcalidrawChange = (elements: readonly any[], appState: any, files: any) => {
        try {
            const jsonState = serializeAsJSON(elements, appState, files, "local");
            console.log("[workspace-tile-canvas] state", jsonState);
        } catch (error) {
            console.error("[workspace-tile-canvas] Failed to serialize state", error);
        }
    };

    public initialize(): void {
        if (!this.element || this.root) return;

        if (!this.element.classList.contains("min-h-64")) {
            this.element.classList.add("min-h-64");
        }

        if (this.element.offsetHeight === 0) {
            this.element.style.height = "24rem";
        }

        if (!this.element.style.position) {
            this.element.style.position = "relative";
        }

        this.root = createRoot(this.element);
        this.root.render(
            createElement(Excalidraw, {
                onChange: this.onExcalidrawChange,
            }),
        );
    }

    public destroy(): void {
        if (this.root) {
            this.root.unmount();
            this.root = null;
        }

        super.destroy();
    }

}
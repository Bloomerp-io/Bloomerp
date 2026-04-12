import BaseComponent from "./BaseComponent";
import grapesjs, { Editor } from "grapesjs";
import presetWebpage from "grapesjs-preset-webpage";

import "grapesjs/dist/css/grapes.min.css";

export default class WebsiteBuilder extends BaseComponent {
    private editor!: Editor;

    public initialize(): void {
        this.editor = grapesjs.init({
            container: `#${this.element.id}`,
            storageManager: false,
            panels: { defaults: [] },

            plugins: [
                presetWebpage
            ],
            pluginsOpts: {
                [presetWebpage as any]: {
                    blocksBasicOpts: { flexGrid: true },
                },
            },
        });
    }
}

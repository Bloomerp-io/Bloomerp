import BaseComponent from "../BaseComponent";
import WorkspaceTile from "./WorkspaceTile";
import htmx from "htmx.org";


const TILE_ENDPOINT = "/components/render_workspace_tile/"

export default class WorkspaceContainer extends BaseComponent {
    private cols: number = 4;
    private tiles: Array<WorkspaceTile> = [];
    private tileSection: HTMLElement | null = null;
    private tileIds: Array<number> = [1,2,3,4,5,6,7,8];
    


    public initialize(): void {
        // Get the tile section element
        this.tileSection = this.element.querySelector("#workspace-tiles-section");
        
        // Send an HTMX request to get the workspace tiles
        for (const tileId of this.tileIds) {
            htmx.ajax("get", TILE_ENDPOINT, {
                target: this.tileSection,
                swap: "beforeend",
                values: { tile_id: tileId },
            });
        }
    }

    getTiles(): Array<WorkspaceTile > {}


    /**
     * 
     * @param cols the number of cols 
     */
    setCols(cols: number): void {}


    /**
     * Removes the tile from the workspace
     * @param tile the tile object
     */
    private removeTile(tile: WorkspaceTile): void {}


    
}
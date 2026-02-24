import BaseComponent from "../BaseComponent";
import WorkspaceTile from "./WorkspaceTile";
import htmx from "htmx.org";


const TILE_ENDPOINT = "/components/render_workspace_tile/"

export default class WorkspaceContainer extends BaseComponent {
    private cols: number = 4;
    private tiles: Array<WorkspaceTile> = [];
    private tileSection: HTMLElement | null = null;
    private tileIds: Array<number> = [];
    private editWorkspaceBtn: HTMLElement | null = null;

    public initialize(): void {
        // Get the tile section element
        this.tileSection = this.element.querySelector("#workspace-tiles-section");
        
        // Set the tile ids
        const tileIdsString = this.element.getAttribute("data-tile-ids") || "";
        this.tileIds = tileIdsString.split(",").map(id => parseInt(id)).filter(id => !isNaN(id));


        // Send an HTMX request to get the workspace tiles
        for (const tileId of this.tileIds) {
            htmx.ajax("get", TILE_ENDPOINT, {
                target: this.tileSection,
                swap: "beforeend",
                values: { tile_id: tileId },
            });
        }

        // Set the button for toggling edit mode
        this.editWorkspaceBtn = this.element.querySelector("#edit-workspace-btn");
        if (this.editWorkspaceBtn) {
            this.editWorkspaceBtn.addEventListener("click", () => this.toggleEditMode());
        }
    }


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


    /**
     * Adds a tile to the workspace. Does this by calling the render_workspace_tile endpoint with the tile ID, which returns the HTML for the tile, and then adds that HTML to the workspace
     * @param tileId the database ID of the tile
     * @param position the position of the tile
     */
    private addTile(tileId: number, position?: number): void {}

    /**
     * Toggles the edit mode of the workspace, allowing the user to add/remove tiles
     */
    private toggleEditMode(): void {
        this.tiles.forEach(tile => {
            tile.setEditMode();
        });
    }


    /**
     * Removes the tile from the workspace
     * @param tile 
     */
    private removeTile(tile: WorkspaceTile): void {}


    /**
     * Saves the state of the workspace, including the order of the tiles and which tiles are included
     */
    private save() : void {}
    
}
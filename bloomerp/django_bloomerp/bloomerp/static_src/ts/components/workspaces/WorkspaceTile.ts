import BaseComponent from "../BaseComponent";

export default class WorkspaceTile extends BaseComponent {
    private colspan: number = 1;
    private icon: string = "";
    private title: string = "";

    public initialize(): void {
    }


    /**
     * Sets the colspan of the workspace tile
     * @param colspan The number of columns the tile should span
     */
    public setColspan(colspan: number): void {}

    /**
     * Sets the icon of the workspace tile
     * @param icon The icon class (e.g. "fa-solid fa-dollar-sign")
     */
    public setIcon(icon: string): void {}

    /**
     * Sets the title of the workspace tile
     * @param title The title of the tile
     */
    public setTitle(title: string): void {}

    

}
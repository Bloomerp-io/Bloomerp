import BaseComponent from "./data_view_components/BaseComponent";

export class DataView extends BaseComponent {
    public initialize(): void {
        
    }

    public destroy(): void {
        console.log('destroyed')
    }
}
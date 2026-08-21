import { BaseDataViewCell } from "./BaseDataViewCell";
import { DataViewContainer } from "./DataViewContainer";

export type ForeignFieldSelection = {
    objectId: string;
    objectString: string;
    detailUrl: string;
};

export default class ForeignFieldDataViewContainer extends DataViewContainer {
    private readonly selectionEventName = 'bloomerp:foreign-field-dataview-select';
    private boundCellDoubleClick: ((event: MouseEvent) => void) | null = null;

    public override initialize(): void {
        super.initialize();
        if (!this.element) return;

        this.boundCellDoubleClick = (event: MouseEvent) => this.handleCellDoubleClick(event);
        this.element.addEventListener('dblclick', this.boundCellDoubleClick, true);
    }

    protected override onCellClick(cell: BaseDataViewCell): boolean {
        if (!cell.element) return super.onCellClick(cell);
        return this.selectCellElement(cell.element);
    }

    public override destroy(): void {
        if (this.element && this.boundCellDoubleClick) {
            this.element.removeEventListener('dblclick', this.boundCellDoubleClick, true);
        }
        super.destroy();
    }

    private handleCellDoubleClick(event: MouseEvent): void {
        const cellElement = (event.target as HTMLElement | null)?.closest<HTMLElement>(
            '[bloomerp-component][data-object-id]',
        );
        if (!cellElement || !this.element?.contains(cellElement)) return;

        if (!this.selectCellElement(cellElement)) return;

        event.preventDefault();
        event.stopPropagation();
    }

    private selectCellElement(cellElement: HTMLElement): boolean {
        const objectId = cellElement.dataset.objectId;
        if (!objectId) return false;

        this.element?.dispatchEvent(new CustomEvent<ForeignFieldSelection>(this.selectionEventName, {
            bubbles: true,
            detail: {
                objectId,
                objectString: cellElement.dataset.objectString || objectId,
                detailUrl: cellElement.dataset.detailUrl || '',
            },
        }));
        return true;
    }
}

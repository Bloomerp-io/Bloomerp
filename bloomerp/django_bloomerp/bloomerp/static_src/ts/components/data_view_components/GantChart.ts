import { BaseDataViewCell } from "./BaseDataViewCell";
import { BaseDataViewComponent } from "./BaseDataViewComponent";

export class GantChartItem extends BaseDataViewCell {
    public initialize(): void {
        
    }
    public destroy(): void {
        
    }
}

export class GantChart extends BaseDataViewComponent {
    protected cellClass = GantChartItem;
    
    moveCellUp(): BaseDataViewCell {
        throw new Error("Method not implemented.");
    }
    moveCellDown(): BaseDataViewCell {
        throw new Error("Method not implemented.");
    }
    
    // No moving left or right with gant charts
    moveCellRight(): BaseDataViewCell {
        return this.currentCell;
    }
    moveCellLeft(): BaseDataViewCell {
        return this.currentCell;
    }
    
}
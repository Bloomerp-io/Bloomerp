export class HtmlHistory {
    private snapshots: string[] = [];
    private index = -1;
    private isRestoring = false;
    private readonly restoreSnapshot: (snapshot: string) => void;

    constructor(restoreSnapshot: (snapshot: string) => void) {
        this.restoreSnapshot = restoreSnapshot;
    }

    capture(snapshot: string, force = false): void {
        if (this.isRestoring) return;

        if (!force && this.snapshots[this.index] === snapshot) {
            return;
        }

        if (this.index < this.snapshots.length - 1) {
            this.snapshots = this.snapshots.slice(0, this.index + 1);
        }

        this.snapshots.push(snapshot);
        this.index = this.snapshots.length - 1;
    }

    undo(): void {
        if (this.index <= 0) return;
        this.index -= 1;
        this.restore(this.snapshots[this.index] || "");
    }

    redo(): void {
        if (this.index >= this.snapshots.length - 1) return;
        this.index += 1;
        this.restore(this.snapshots[this.index] || "");
    }

    private restore(snapshot: string): void {
        this.isRestoring = true;
        this.restoreSnapshot(snapshot);
        this.isRestoring = false;
    }
}

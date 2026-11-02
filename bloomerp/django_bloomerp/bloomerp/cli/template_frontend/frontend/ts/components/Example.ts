import { BaseComponent } from '@bloomerp/frontend';

export class Example extends BaseComponent {
    /** Mark this app-owned component ready after its fields and registry are initialized. */
    public override initialize(): void {
        this.element?.setAttribute('data-example-ready', 'true');
    }
}

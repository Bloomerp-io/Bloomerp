import { BaseComponent, getComponent, initComponents, registerComponent } from '../dist/index.js';

class CustomComponent extends BaseComponent {
    /** Verify implementation subclasses can use the public element and lifecycle. */
    public override initialize(): void {
        this.element?.setAttribute('data-ready', 'true');
    }

    /** Verify lifecycle overrides remain available without internal imports. */
    public override onAfterSwap(): void {
        this.initialize();
    }
}

registerComponent('contract:custom', CustomComponent);
registerComponent('contract:custom', CustomComponent, { override: true });
const element = document.createElement('div');
const component: BaseComponent | null = getComponent(element);
initComponents(element);
component?.getDataAttribute('ready');

import { componentIdentifier, getComponent } from "../components/BaseComponent";
import { MessageType } from "../components/UiMessage";

export default function showMessage(
    messageText: string,
    messageType: MessageType = MessageType.INFO,
    duration: number = 5,
): void {
    // Create a host element and set data attributes consumed by UiMessage
    const host = document.createElement('div');
    host.setAttribute(componentIdentifier, 'ui-message');
    host.dataset.messageText = messageText;
    host.dataset.messageType = messageType as string;
    host.dataset.duration = String(duration);
    // Mark host for auto-removal by the component after message is dismissed
    host.dataset.autoRemove = 'true';

    // Append to body so UiMessage can position itself via its wrapper
    document.body.appendChild(host);

    // Initialize the component (uses registered component constructor)
    // getComponent will instantiate and call initialize()
    getComponent(host);
}
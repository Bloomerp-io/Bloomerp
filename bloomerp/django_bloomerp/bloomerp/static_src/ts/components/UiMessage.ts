import BaseComponent from "./BaseComponent"

export enum MessageType {
    INFO = "info",
    SUCCESS = "success",
    WARNING = "warning",
    ERROR = "error"
}


export default class UiMessage extends BaseComponent {
    private messageText: string;
    private messageType: MessageType;
    private duration: number = 5;
    private position: string = "bottom-right";

    public initialize(): void {
        this.messageText = this.element.dataset.messageText || "";
        this.messageType = (this.element.dataset.messageType as MessageType) || MessageType.INFO;
        this.position = this.element.dataset.position || this.position;
        const durationData = this.element.dataset.duration;
        if (durationData) {
            this.duration = parseInt(durationData, 10);
        }

        this.showMessage();
    }

    /**
     * Method to show the actual message on the screen
     */
    public showMessage(): void {
        const messageContainer = document.createElement("div");
        // Map logical message types to Tailwind color names
        const colorMap: Record<MessageType, string> = {
            [MessageType.INFO]: "blue",
            [MessageType.SUCCESS]: "green",
            [MessageType.WARNING]: "amber",
            [MessageType.ERROR]: "red",
        };

        const color = colorMap[this.messageType] || "blue";

        messageContainer.classList.add(
            `bg-${color}-100`,
            `border-${color}-400`,
            `text-${color}-800`,
            "px-4",
            "py-3",
            "rounded",
            "shadow-md",
            "my-2",
            "message-container",
            "alert-message"
        );

        // Add a specific alert class so custom CSS can also target it
        messageContainer.classList.add(`alert-message-${this.messageType}`);

        // Create message inside the element with an icon and close button
        const left = document.createElement('div');
        left.classList.add('flex', 'items-center');

        const iconElem = document.createElement('i');
        iconElem.classList.add('alert-icon');
        // Map to Font Awesome icons (common names)
        const iconMap: Record<MessageType, string[]> = {
            [MessageType.INFO]: ['fa-solid', 'fa-info-circle'],
            [MessageType.SUCCESS]: ['fa-solid', 'fa-check-circle'],
            [MessageType.WARNING]: ['fa-solid', 'fa-exclamation-triangle'],
            [MessageType.ERROR]: ['fa-solid', 'fa-exclamation-circle'],
        };
        const faClasses = iconMap[this.messageType] || iconMap[MessageType.INFO];
        faClasses.forEach((c) => iconElem.classList.add(c));

        const textElem = document.createElement('div');
        textElem.classList.add('ml-3');
        textElem.textContent = this.messageText;

        left.appendChild(iconElem);
        left.appendChild(textElem);

        const closeBtn = document.createElement('button');
        closeBtn.classList.add('alert-close');
        closeBtn.setAttribute('aria-label', 'Dismiss message');
        closeBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';

        // Container layout: left (icon+text) and right (close)
        messageContainer.appendChild(left);
        messageContainer.appendChild(closeBtn);

        // Append to a fixed-position wrapper so messages are fixed in place
        const wrapper = this.getOrCreateWrapper(this.position);
        wrapper.appendChild(messageContainer);

        // Remove the message after the specified duration with a fade-out
        let removalTimer = window.setTimeout(() => {
            fadeOutAndRemove();
        }, this.duration * 1000);

        // Close button dismisses immediately
        closeBtn.addEventListener('click', () => {
            window.clearTimeout(removalTimer);
            fadeOutAndRemove();
        });

        const fadeOutAndRemove = (): void => {
            messageContainer.classList.add('fade-out');
            setTimeout(() => {
                messageContainer.remove();
                // If the host element was created programmatically and marked
                // for auto removal, remove it too to avoid leaks.
                if (this.element && this.element.dataset && this.element.dataset.autoRemove === 'true') {
                    this.element.remove();
                }
            }, 500);
        };

    }

    private getOrCreateWrapper(position: string): HTMLElement {
        const id = `messages-wrapper-${position}`;
        let wrapper = document.getElementById(id) as HTMLElement | null;
        if (wrapper) return wrapper;

        wrapper = document.createElement("div");
        wrapper.id = id;
        wrapper.classList.add("messages-wrapper");
        // Set position defaults; override the CSS .messages-wrapper base anchors
        wrapper.style.position = "fixed";
        wrapper.style.zIndex = "1100";
        wrapper.style.display = "flex";
        wrapper.style.flexDirection = "column";
        wrapper.style.gap = "10px";

        // Position mapping
        switch (position) {
            case "top-right":
                wrapper.style.top = "40px";
                wrapper.style.right = "60px";
                wrapper.style.left = "auto";
                wrapper.style.bottom = "auto";
                break;
            case "bottom-left":
                wrapper.style.bottom = "40px";
                wrapper.style.left = "60px";
                wrapper.style.top = "auto";
                wrapper.style.right = "auto";
                break;
            case "bottom-right":
                wrapper.style.bottom = "40px";
                wrapper.style.right = "60px";
                wrapper.style.top = "auto";
                wrapper.style.left = "auto";
                break;
            case "top-left":
            default:
                wrapper.style.top = "40px";
                wrapper.style.left = "60px";
                wrapper.style.right = "auto";
                wrapper.style.bottom = "auto";
                break;
        }

        document.body.appendChild(wrapper);
        return wrapper;
    }

}
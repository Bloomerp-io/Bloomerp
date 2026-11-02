/**
 * Messages module for Bloomerp application.
 */
import showMessage from '../utils/messages';
import { MessageType } from '../components/UiMessage';

type MessagePayload = {
    action?: string;
    notification_count?: number;
    type: "toast" | "inbox_notification";
    data: ToastPayload | NotificationPayload;
}

type ToastPayload = {
    message?: string;
    message_type?: string;
    duration?: number;
};

type NotificationPayload = {
    notification_count?: number;
    toast_payload?: ToastPayload;
}

let notificationAudio: HTMLAudioElement | null = null;

const coerceMessageType = (value?: string): MessageType => {
    switch ((value || '').toLowerCase()) {
        case 'success':
            return MessageType.SUCCESS;
        case 'warning':
            return MessageType.WARNING;
        case 'danger':
            return MessageType.ERROR;
        case 'error':
            return MessageType.ERROR;
        case 'info':
        default:
            return MessageType.INFO;
    }
};

const handleToast = (payload: ToastPayload): void => {
    const message = payload.message;
    if (!message) {
        return;
    }

    const messageType = coerceMessageType(payload.message_type);
    const duration = payload.duration ?? 5;

    showMessage(message, messageType, duration);
};

/**
 * Plays the notification sound resolved by Django's staticfiles system.
 */
const playNotificationSound = (): void => {
    const soundUrl = document.querySelector<HTMLMetaElement>(
        'meta[name="bloomerp-message-sound-url"]'
    )?.content;
    if (!soundUrl) {
        return;
    }

    notificationAudio ??= new Audio(soundUrl);
    notificationAudio.currentTime = 0;
    void notificationAudio.play().catch((error: unknown) => {
        console.warn('Failed to play notification sound', error);
    });
};

const handleNotification = (payload: NotificationPayload): void => {
    playNotificationSound();

    const toastPayload = payload.toast_payload;
    if (!toastPayload || !toastPayload.message) {
        return;
    }

    const messageType = coerceMessageType(toastPayload.message_type);
    const duration = toastPayload.duration ?? 5;

    showMessage(toastPayload.message, messageType, duration, true);

    const notificationCountEl = document.getElementById('inbox-notification-count');
    if (notificationCountEl && payload.notification_count !== undefined) {
        notificationCountEl.textContent = payload.notification_count.toString();
    }



};


/** Keep authenticated notifications and call invitations connected across network interruptions. */
export const initMessagesWebsocket = (): void => {
    if (typeof window === 'undefined') return;
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const wsUrl = `${protocol}://${window.location.host}/ws/notifications/`;
    let socket: WebSocket | null = null;
    let retry: number | null = null;
    let delay = 1000;
    let stopped = false;

    /** Expose signaling readiness to the shared calling panel without exposing socket objects. */
    function signaling(state: 'connected' | 'connecting' | 'disconnected'): void {
        document.body.dataset.callSignalingState = state;
        document.dispatchEvent(new CustomEvent('bloomerp:calling-signaling'));
    }

    /** Dispatch existing notification and call payloads through their shared UI events. */
    function onMessage(event: MessageEvent<string>): void {
        try {
            const data = JSON.parse(event.data) as MessagePayload;
            if (data.action === 'conferencing.session.changed') {
                document.dispatchEvent(new CustomEvent('im:call-changed', { detail: data }));
            } else if (data.action === 'im.message.created' || data.action === 'im.read.updated' || data.action === 'im.group.updated') {
                const counter = document.getElementById('inbox-notification-count');
                if (counter && data.notification_count !== undefined) {
                    counter.textContent = data.notification_count > 0 ? String(data.notification_count) : '';
                }
                document.body.dispatchEvent(new CustomEvent('im:unread-changed', { bubbles: true }));
            } else if (data.type === 'inbox_notification') {
                handleNotification(data.data as NotificationPayload);
            } else if (data.type === 'toast') {
                handleToast(data.data as ToastPayload);
            }
        } catch (error) {
            console.warn('Failed to parse websocket message', error);
        }
    }

    /** Reopen the authenticated notification socket after a bounded reconnect delay. */
    function connect(): void {
        if (stopped || (socket && socket.readyState < WebSocket.CLOSING)) return;
        if (retry !== null) window.clearTimeout(retry);
        retry = null;
        signaling('connecting');
        socket = new WebSocket(wsUrl);
        socket.addEventListener('message', onMessage);
        socket.addEventListener('open', onOpen);
        socket.addEventListener('close', onClose);
        socket.addEventListener('error', onError);
    }

    /** Mark both ordinary notifications and video-call invitations ready for delivery. */
    function onOpen(): void { delay = 1000; signaling('connected'); }

    /** Retry transient loss while avoiding retries after the application unloads. */
    function onClose(): void {
        signaling('disconnected');
        if (stopped || retry !== null) return;
        retry = window.setTimeout(connect, delay);
        delay = Math.min(30000, delay * 2);
    }

    /** Close a failed socket so one reconnect path handles all transport failures. */
    function onError(): void { socket?.close(); }

    /** Release signaling resources when the owning document actually leaves. */
    function onPageHide(): void {
        stopped = true;
        if (retry !== null) window.clearTimeout(retry);
        retry = null;
        socket?.close();
    }

    /** Restore notification delivery when a browser returns a cached document. */
    function onPageShow(event: PageTransitionEvent): void {
        if (event.persisted) { stopped = false; connect(); }
    }

    window.addEventListener('online', connect);
    window.addEventListener('pagehide', onPageHide);
    window.addEventListener('pageshow', onPageShow);
    connect();
};
